"""
Agent 主循环模块 (Agent Loop)
- 编排完整审查流程
- 与 Chat Memory 协同支持多轮交互
- 进度回调机制
"""

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from src.chat_memory import ChatMemory
from src.logger import logger_manager


class TaskStage(Enum):
    """任务阶段"""

    INIT = "init"
    PARSING = "parsing"
    SECURITY_CHECK = "security_check"
    RULE_ANALYSIS = "rule_analysis"
    LLM_ANALYSIS = "llm_analysis"
    LEGAL_MATCH = "legal_match"
    REPORT_GEN = "report_generation"
    REVISION_GEN = "revision_generation"
    COMPLETE = "complete"
    ERROR = "error"


STAGE_NAMES = {
    TaskStage.INIT: "初始化",
    TaskStage.PARSING: "文件解析",
    TaskStage.SECURITY_CHECK: "安全检查",
    TaskStage.RULE_ANALYSIS: "规则分析",
    TaskStage.LLM_ANALYSIS: "AI 深度分析",
    TaskStage.LEGAL_MATCH: "法条匹配",
    TaskStage.REPORT_GEN: "生成报告",
    TaskStage.REVISION_GEN: "生成修订建议",
    TaskStage.COMPLETE: "审查完成",
    TaskStage.ERROR: "出错",
}


@dataclass
class TaskProgress:
    """任务进度"""

    stage: TaskStage
    stage_name: str
    percentage: float  # 0-100
    message: str
    detail: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReviewTask:
    """审查任务"""

    task_id: str
    session_id: str
    status: str = "pending"  # pending / running / completed / failed / cancelled
    progress: TaskProgress | None = None
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


class AgentLoop:
    """
    Agent 主循环

    编排从文件上传到报告生成的完整流程，
    支持进度回调、中断恢复和多轮对话。
    """

    def __init__(
        self,
        chat_memory: ChatMemory,
        parser,
        security,
        risk_engine,
        legal_matcher,
        report_gen,
        redliner=None,
        llm_client_factory=None,
    ):
        """
        初始化 Agent 循环

        Args:
            chat_memory: 对话记忆管理器
            parser: 文档解析器
            security: 安全预处理器
            risk_engine: 风险识别引擎
            legal_matcher: 法条匹配器
            report_gen: 报告生成器
            redliner: 修订生成器（可选）
            llm_client_factory: LLM 客户端工厂函数
        """
        self.chat_memory = chat_memory
        self.parser = parser
        self.security = security
        self.risk_engine = risk_engine
        self.legal_matcher = legal_matcher
        self.report_gen = report_gen
        self.redliner = redliner
        self.llm_client_factory = llm_client_factory

        self.tasks: dict[str, ReviewTask] = {}
        self._tasks_lock = threading.Lock()
        self._max_tasks = 50  # 最大保留任务数
        self.logger = logger_manager

    async def start_review(
        self,
        file_bytes: bytes,
        filename: str,
        document_type: str = "auto_detect",
        playbook_id: str = "neutral",
        use_llm: bool = True,
        special_requirements: str = "",
        session_id: str | None = None,
        progress_callback: Callable[[TaskProgress], None] | None = None,
    ) -> dict:
        """
        启动审查任务

        Args:
            file_bytes: 文件字节流
            filename: 文件名
            document_type: 文档类型
            playbook_id: 审查策略 ID
            use_llm: 是否使用 LLM
            special_requirements: 特殊要求
            session_id: 会话 ID（可选）
            progress_callback: 进度回调函数

        Returns:
            审查结果字典
        """
        import uuid

        task_id = str(uuid.uuid4())[:12]

        task = ReviewTask(task_id=task_id, session_id=session_id or "standalone")
        with self._tasks_lock:
            self._cleanup_old_tasks()
            self.tasks[task_id] = task

        self.logger.audit_file_upload(filename, len(file_bytes), filename.split(".")[-1])
        self.logger.audit_review_start(filename, document_type, playbook_id, use_llm)

        start_time = time.time()

        try:
            task.status = "running"
            task.started_at = time.time()

            result = await self._execute_review(
                file_bytes=file_bytes,
                filename=filename,
                document_type=document_type,
                playbook_id=playbook_id,
                use_llm=use_llm,
                special_requirements=special_requirements,
                task=task,
                progress_callback=progress_callback,
            )

            task.status = "completed"
            task.result = result
            task.completed_at = time.time()

            duration = time.time() - start_time
            self.logger.audit_review_complete(
                filename,
                result.get("risk_summary", {}).get("total", 0),
                result.get("risk_summary", {}).get("high", 0),
                duration,
            )

            return result

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = time.time()
            self.logger.error(f"审查任务失败 [{task_id}]: {e}", exc_info=True)

            if progress_callback:
                progress_callback(
                    TaskProgress(stage=TaskStage.ERROR, stage_name="出错", percentage=0, message=f"审查失败: {str(e)}")
                )

            raise

    async def _execute_review(
        self,
        file_bytes: bytes,
        filename: str,
        document_type: str,
        playbook_id: str,
        use_llm: bool,
        special_requirements: str,
        task: ReviewTask,
        progress_callback: Callable | None,
    ) -> dict:
        """执行审查流程"""

        # Stage 1: 文件解析 (10%)
        await self._update_progress(task, TaskStage.PARSING, 10, f"正在解析文件: {filename}", progress_callback)
        parsed_doc = self.parser.parse_bytes(file_bytes, filename)
        text = parsed_doc.full_text

        # 自动检测文档类型
        if document_type == "auto_detect":
            document_type = self.risk_engine.detect_document_type(text)

        # 拦截非法律文件
        if document_type == "unknown":
            self.logger.info(f"文档类型检测: 非法律文件，已拦截 - {filename}")
            return {
                "status": "not_legal_document",
                "message": (
                    "⚠️ 该文档不像是一份法律文件（合同、协议、隐私政策等）。\n\n"
                    "本系统专门用于审查法律文件，请上传以下类型的文档：\n"
                    "- 📄 合同 / 协议\n"
                    "- 📄 隐私政策 / 用户协议\n"
                    "- 📄 保密协议 / 授权委托书\n"
                    "- 📄 其他法律文书\n\n"
                    "如果您确认这是一份法律文件，可以在左侧手动选择文档类型后重试。"
                ),
                "risk_summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
                "risks": [],
                "document_type": "unknown",
            }

        # Stage 2: 安全检查 (25%)
        await self._update_progress(task, TaskStage.SECURITY_CHECK, 25, "正在进行安全检查", progress_callback)
        security_result = self.security.check_text(text)

        if security_result.out_of_scope:
            return {
                "status": "out_of_scope",
                "message": security_result.out_of_scope_reason,
                "security_warning": security_result.risk_warning,
            }

        # 获取策略
        try:
            playbook = self.risk_engine.playbook_manager.get_playbook(playbook_id)
        except KeyError:
            playbook = self.risk_engine.playbook_manager.get_playbook("neutral")

        # Stage 3: 规则分析 (45%)
        await self._update_progress(task, TaskStage.RULE_ANALYSIS, 45, "正在进行规则分析", progress_callback)
        risk_result = self.risk_engine.analyze_by_rules(text, document_type, playbook)

        # Stage 4: LLM 分析 (65%)
        llm_warnings = []
        tool_call_log = []  # 工具调用日志

        if use_llm and self.llm_client_factory:
            await self._update_progress(task, TaskStage.LLM_ANALYSIS, 65, "正在进行 AI 深度分析", progress_callback)
            llm_client = None
            try:
                llm_client = self.llm_client_factory()

                # 包装进度回调，收集工具调用日志
                def on_tool_event(event: dict):
                    tool_call_log.append(
                        {
                            "risk_name": event.get("risk_name", ""),
                            "tool": event.get("tool", "AI 推理"),
                            "status": event.get("type", ""),
                            "detail": event.get("content", "")[:150],
                        }
                    )

                    if progress_callback:
                        stage_msg = {
                            "tool_call": f"🤖 AI 正在调用 {event.get('tool', '')}...",
                            "tool_result": f"✅ {event.get('tool', '')} 返回结果",
                            "interrupted": f"🛑 {event.get('content', '')[:100]}",
                            "reflection": f"🔍 自我反思：{event.get('content', '')[:100]}",
                        }.get(event.get("type", ""), event.get("content", ""))

                        progress_callback(
                            TaskProgress(
                                stage=TaskStage.LLM_ANALYSIS, stage_name="AI 深度分析", percentage=65, message=stage_msg
                            )
                        )

                llm_risk_result = await self.risk_engine.analyze_with_llm(
                    text, document_type, llm_client, playbook, progress_callback=on_tool_event
                )
                # 合并结果
                risk_result.risks.extend(llm_risk_result.risks)
                risk_result.high_count += llm_risk_result.high_count
                risk_result.medium_count += llm_risk_result.medium_count
                risk_result.low_count += llm_risk_result.low_count

                # 去重：规则分析和 LLM 分析可能识别同一风险
                risk_result.risks = self.risk_engine.deduplicate_risks(risk_result.risks)
                # 重新统计
                risk_result.critical_count = sum(1 for r in risk_result.risks if r.risk_level == "critical")
                risk_result.high_count = sum(1 for r in risk_result.risks if r.risk_level == "high")
                risk_result.medium_count = sum(1 for r in risk_result.risks if r.risk_level == "medium")
                risk_result.low_count = sum(1 for r in risk_result.risks if r.risk_level == "low")
            except Exception as e:
                # 降级策略：记录警告，继续使用规则分析结果
                from src.exceptions import classify_error, get_user_friendly_message

                error_code = classify_error(e)
                user_msg = get_user_friendly_message(error_code)
                llm_warnings.append(f"⚠️ {user_msg}，已使用规则分析结果")
                self.logger.warning(f"LLM 分析降级: {e}")
            finally:
                if llm_client is not None:
                    try:
                        llm_client.close()
                    except Exception:
                        pass

        # Stage 5: 法条匹配 (80%)
        await self._update_progress(task, TaskStage.LEGAL_MATCH, 80, "正在匹配相关法条", progress_callback)
        all_legal_matches = []
        for risk in risk_result.risks:
            if risk.legal_basis:
                matches = self.legal_matcher.match_provisions(risk.description, risk.category)
                all_legal_matches.extend(matches)
                # 记录引用的法条（溯源）
                for m in matches[:2]:  # 最多引用2条
                    risk.cited_provisions.append(f"《{m.provision.law}》{m.provision.article}")

        # 溯源关联：将风险项关联回原始条款
        risk_result.risks = self.risk_engine.link_risks_to_clauses(risk_result.risks, parsed_doc.clauses)

        # Stage 6: 生成报告 (90%)
        await self._update_progress(task, TaskStage.REPORT_GEN, 90, "正在生成审查报告", progress_callback)
        report_md = self.report_gen.generate_report(
            document_name=filename,
            document_type=document_type,
            risk_result=risk_result,
            legal_matches=all_legal_matches,
            security_warning=security_result.risk_warning,
            sensitive_items=security_result.sensitive_items,
        )
        report_dict = self.report_gen.generate_report_dict(
            document_name=filename,
            document_type=document_type,
            risk_result=risk_result,
            legal_matches=all_legal_matches,
            security_warning=security_result.risk_warning,
            sensitive_items=security_result.sensitive_items,
        )

        # Stage 7: 生成修订建议（可选，95%）
        revisions_html = ""
        docx_bytes = None
        if self.redliner and risk_result.risks:
            await self._update_progress(task, TaskStage.REVISION_GEN, 95, "正在生成修订建议", progress_callback)
            try:
                if use_llm and self.llm_client_factory:
                    llm_client = self.llm_client_factory()
                    self.redliner.set_llm_client(llm_client)

                revision_doc = await self.redliner.generate_revisions(text, risk_result.risks, playbook)
                revisions_html = revision_doc.html_full_diff

                # 生成 DOCX
                if revision_doc.revisions:
                    docx_bytes = self.redliner.generate_docx_with_revisions(text, revision_doc.revisions, filename)
            except Exception as e:
                # 降级策略：记录警告，但不阻断流程
                from src.exceptions import classify_error, get_user_friendly_message

                error_code = classify_error(e)
                user_msg = get_user_friendly_message(error_code)
                llm_warnings.append(f"📝 {user_msg}")
                self.logger.warning(f"修订建议生成降级: {e}")

        # Complete (100%)
        await self._update_progress(task, TaskStage.COMPLETE, 100, "审查完成", progress_callback)

        # 构建结果
        if not risk_result.risks:
            llm_warnings.append("✅ 审查完成，未发现风险点（仍建议专业律师复核）")

        result = {
            **report_dict,
            "report_markdown": report_md,
            "revisions_html": revisions_html,
            "docx_available": docx_bytes is not None,
            "warnings": llm_warnings,
            "security_warning": security_result.risk_warning,
            "tool_call_log": tool_call_log,
            "sensitive_items": [
                {"type": item.type, "masked_value": item.masked_value} for item in security_result.sensitive_items
            ],
            "document_type": document_type,
            "playbook_id": playbook_id,
            # 溯源数据
            "clauses": [
                {"id": c.id, "title": c.title or f"第{c.id}条", "content": c.content, "clause_type": c.clause_type}
                for c in parsed_doc.clauses
            ],
            "original_text": text,  # 用于高亮显示
        }

        if docx_bytes:
            result["docx_bytes"] = docx_bytes

        return result

    async def _update_progress(
        self, task: ReviewTask, stage: TaskStage, percentage: float, message: str, callback: Callable | None
    ):
        """更新任务进度"""
        progress = TaskProgress(stage=stage, stage_name=STAGE_NAMES[stage], percentage=percentage, message=message)
        task.progress = progress

        if callback:
            if asyncio.iscoroutinefunction(callback):
                await callback(progress)
            else:
                callback(progress)

        # 短暂暂停让 UI 有机会更新
        await asyncio.sleep(0.1)

    def _cleanup_old_tasks(self):
        """清理已完成的旧任务，防止内存无限增长（需在 _tasks_lock 下调用）"""
        done_statuses = {"completed", "failed", "cancelled"}
        done_tasks = [(tid, t) for tid, t in self.tasks.items() if t.status in done_statuses]
        if len(done_tasks) > self._max_tasks // 2:
            done_tasks.sort(key=lambda x: x[1].completed_at or 0)
            for tid, _ in done_tasks[: len(done_tasks) // 2]:
                del self.tasks[tid]

    def get_task(self, task_id: str) -> ReviewTask | None:
        """获取任务状态"""
        with self._tasks_lock:
            return self.tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._tasks_lock:
            task = self.tasks.get(task_id)
            if task and task.status in ("pending", "running"):
                task.status = "cancelled"
                return True
            return False

    def list_tasks(self, limit: int = 10) -> list[dict]:
        """列出最近任务"""
        with self._tasks_lock:
            sorted_tasks = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)
            return [
                {
                    "task_id": t.task_id,
                    "status": t.status,
                    "progress": t.progress.percentage if t.progress else 0,
                    "created_at": t.created_at,
                    "error": t.error,
                }
                for t in sorted_tasks[:limit]
            ]
