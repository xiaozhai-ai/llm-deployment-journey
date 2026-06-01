"""
业务逻辑处理器

封装审查流程、对话、反馈等 Gradio 事件回调，
将 UI 布局与业务逻辑解耦。
"""

import asyncio
import atexit
import os
import signal
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import gradio as gr

from src.agent_loop import AgentLoop, TaskProgress
from src.exceptions import (
    FileCorruptedError,
    LLMError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMTimeoutError,
    ParsingError,
    UnsupportedFormatError,
    classify_error,
    get_user_friendly_message,
)
from src.html_renderers import format_thinking_process, format_tool_call_log
from src.logger import logger_manager
from src.session_store import review_store

_executor = ThreadPoolExecutor(max_workers=4)


# 进程退出时清理残留临时文件
_temp_files: set = set()
_temp_files_lock = threading.Lock()


def _cleanup_temp_files():
    with _temp_files_lock:
        paths = list(_temp_files)
        _temp_files.clear()
    for path in paths:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_temp_files)
atexit.register(lambda: _executor.shutdown(wait=False))
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, lambda s, f: (_cleanup_temp_files(), signal.default_int_handler(s, f)))
    except (OSError, ValueError):
        pass  # 非主线程无法设置信号


def _run_async_in_thread(coro):
    """在独立线程中运行协程，避免与当前线程已有的事件循环冲突"""
    future = _executor.submit(asyncio.run, coro)
    return future.result()


# ============================================
# 审查流程
# ============================================


async def run_review(
    file,
    document_type: str,
    playbook_id: str,
    use_llm: bool,
    special_requirements: str,
    agent_loop: AgentLoop,
    max_file_size_mb: int = 10,
    progress_callback=None,
) -> dict:
    """执行审查流程"""
    if file is None:
        raise ValueError("请先上传文件")

    if hasattr(file, "size") and file.size > max_file_size_mb * 1024 * 1024:
        raise ValueError(f"文件大小超过限制（{max_file_size_mb}MB）")

    filename = file.name
    with open(file.name, "rb") as f:
        file_bytes = f.read()

    return await agent_loop.start_review(
        file_bytes=file_bytes,
        filename=filename,
        document_type=document_type,
        playbook_id=playbook_id,
        use_llm=use_llm,
        special_requirements=special_requirements,
        progress_callback=progress_callback,
    )


def make_review_handler(agent_loop: AgentLoop, max_file_size_mb: int = 10):
    """
    工厂函数：生成带流式输出的审查处理器（供 Gradio 调用）

    返回一个 generator 函数，使用 yield 实现实时思考过程更新。
    """

    def review_with_progress(
        file, document_type: str, playbook_id: str, use_llm: bool, special_requirements: str, progress=gr.Progress()
    ):
        thinking_steps = []
        thinking_html = '<div class="thinking-panel">⏳ 正在初始化审查...</div>'

        async def run_review_with_streaming():
            nonlocal thinking_html

            def on_progress(p: TaskProgress):
                nonlocal thinking_html
                if p.stage_name == "AI 深度分析":
                    thinking_steps.append(p.message)
                    thinking_html = format_thinking_process(thinking_steps)

            return await run_review(
                file,
                document_type,
                playbook_id,
                use_llm,
                special_requirements,
                agent_loop=agent_loop,
                max_file_size_mb=max_file_size_mb,
                progress_callback=on_progress,
            )

        yield thinking_html, "", "", "", "", None

        docx_file = None
        try:
            result = _run_async_in_thread(run_review_with_streaming())

            # 非法律文件拦截
            if result.get("status") == "not_legal_document":
                msg = result.get("message", "该文档不是法律文件")
                yield ('<div class="thinking-panel">⚠️ 文档类型检测：非法律文件</div>', msg, "", "", "", None)
                return

            report_md = result.get("report_markdown", "")
            warnings = "\n\n".join(result.get("warnings", []))
            if result.get("security_warning"):
                warnings = (warnings + "\n\n" + result["security_warning"]).strip()

            revisions_html = result.get("revisions_html", "")
            thinking_html = format_thinking_process(thinking_steps)
            tool_log_html = format_tool_call_log(result.get("tool_call_log", []))

            if result.get("docx_available") and result.get("docx_bytes"):
                tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
                tmp.write(result["docx_bytes"])
                tmp.close()
                docx_file = tmp.name
                with _temp_files_lock:
                    _temp_files.add(docx_file)

            session_id = review_store.create_session()
            review_store.update(
                session_id,
                {
                    "clauses": result.get("clauses", []),
                    "risks": result.get("risks", []),
                    "document_type": result.get("document_type", ""),
                    "playbook_id": result.get("playbook_id", ""),
                    "filename": result.get("document_name", ""),
                    "original_text": result.get("original_text", ""),
                },
            )
            result["_session_id"] = session_id

            yield thinking_html, report_md, warnings, tool_log_html, revisions_html, docx_file

        except UnsupportedFormatError as e:
            logger_manager.warning(f"文件格式错误: {e}")
            yield (
                f'<div class="thinking-panel">{get_user_friendly_message(classify_error(e))}</div>',
                "",
                "",
                "",
                "",
                None,
            )
        except FileCorruptedError as e:
            logger_manager.warning(f"文件损坏: {e}")
            yield (
                f'<div class="thinking-panel">{get_user_friendly_message(classify_error(e))}</div>',
                "",
                "",
                "",
                "",
                None,
            )
        except LLMTimeoutError as e:
            logger_manager.warning(f"LLM 超时: {e}")
            yield (
                format_thinking_process(thinking_steps),
                f"⚠️ {get_user_friendly_message(classify_error(e))}",
                "",
                "",
                "",
                None,
            )
        except LLMError as e:
            logger_manager.error(f"LLM 错误: {e}")
            yield (
                format_thinking_process(thinking_steps),
                f"⚠️ {get_user_friendly_message(classify_error(e))}",
                "",
                "",
                "",
                None,
            )
        except ParsingError as e:
            logger_manager.error(f"解析错误: {e}")
            yield (
                f'<div class="thinking-panel">{get_user_friendly_message(classify_error(e))}</div>',
                "",
                "",
                "",
                "",
                None,
            )
        except Exception as e:
            logger_manager.error(f"审查失败: {e}", exc_info=True)
            yield (
                f'<div class="thinking-panel">❌ 审查失败：{get_user_friendly_message(classify_error(e))}</div>',
                "",
                "",
                "",
                "",
                None,
            )
        finally:
            # 不在此处删除临时文件：Gradio gr.File 组件在用户点击下载时才读取文件，
            # 提前删除会导致下载失败。临时文件由 atexit 的 _cleanup_temp_files 统一清理。
            pass

    return review_with_progress


# ============================================
# 多轮对话（流式输出）
# ============================================

_MAX_CHAT_INPUT_LEN = 2000
_MAX_HISTORY_MESSAGES = 6  # 发送给 LLM 的最大历史消息数
_CHAT_SYSTEM_PROMPT = "法务审查助手，解答法律文件审查疑问。建议仅供参考，不构成法律意见。回答简洁专业。"

# 快速关键词回复：命中时直接返回，无需调用 LLM
_QUICK_REPLIES = {
    "合同": "好的，请上传合同或协议文件（PDF/Word/TXT），我会为您进行风险审查。",
    "协议": "好的，请上传合同或协议文件（PDF/Word/TXT），我会为您进行风险审查。",
    "风险": "请先在左侧上传文件，然后选择审查策略，点击「开始审查」即可。",
    "审查": "请先在左侧上传文件，然后选择审查策略，点击「开始审查」即可。",
    "甲方": "您可以在「审查策略」中选择「甲方立场」或「乙方立场」，系统会根据您的立场调整审查重点。",
    "乙方": "您可以在「审查策略」中选择「甲方立场」或「乙方立场」，系统会根据您的立场调整审查重点。",
}


def _build_llm_messages(history: list, user_message: str) -> list:
    """构建发送给 LLM 的消息列表，裁剪历史以控制 token 消耗"""
    trimmed = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history
    messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
    for msg in trimmed:
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    return messages


def _quick_reply(message: str):
    """检查是否命中快速关键词回复"""
    for keyword, reply in _QUICK_REPLIES.items():
        if keyword in message:
            return reply
    return None


def make_chat_handler(llm_client_factory, llm_api_key: str):
    """
    工厂函数：生成流式对话处理器（generator，供 Gradio Chatbot 调用）

    优化点：
    1. 流式输出 — 用户立即看到逐字生成效果
    2. 同步 SSE — 避免 asyncio.run + 线程池 3 层开销
    3. 历史裁剪 — 只发送最近 N 条消息给 LLM
    4. 快速回复 — 常见问题无需调用 LLM
    """
    _cached_client = None

    def _get_client():
        nonlocal _cached_client
        if _cached_client is None:
            _cached_client = llm_client_factory()
        return _cached_client

    def chat_respond(message: str, history: list):
        if not message:
            yield history
            return

        if len(message) > _MAX_CHAT_INPUT_LEN:
            history.append({"role": "user", "content": message})
            history.append(
                {
                    "role": "assistant",
                    "content": f"⚠️ 消息过长（{len(message)} 字符），请控制在 {_MAX_CHAT_INPUT_LEN} 字符以内。",
                }
            )
            yield history
            return

        # 快速关键词回复（无需 LLM，始终优先）
        quick = _quick_reply(message)
        if quick:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": quick})
            yield history
            return

        # 流式 LLM 回复
        if llm_api_key:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": ""})

            try:
                client = _get_client()
                llm_messages = _build_llm_messages(history[:-2], message)

                accumulated = ""
                for chunk in client.stream_chat_completion_sync(
                    messages=llm_messages, temperature=0.7, max_tokens=800, timeout=30
                ):
                    accumulated += chunk
                    history[-1] = {"role": "assistant", "content": accumulated}
                    yield history

                # 流式无内容时降级到非流式
                if not accumulated:
                    reply = _run_async_in_thread(
                        client.chat_completion(messages=llm_messages, temperature=0.7, max_tokens=800)
                    )
                    history[-1] = {"role": "assistant", "content": reply}
                    yield history

            except LLMTimeoutError:
                logger_manager.warning("LLM 对话超时")
                history[-1] = {
                    "role": "assistant",
                    "content": "⏱️ AI 服务响应超时，请稍后重试。您可以先上传文件进行规则分析。",
                }
                yield history
            except LLMRateLimitError:
                logger_manager.warning("LLM 频率限制")
                history[-1] = {"role": "assistant", "content": "🔄 AI 服务繁忙，请稍后重试。"}
                yield history
            except (LLMNetworkError, LLMError) as e:
                logger_manager.warning(f"LLM 对话错误: {e}")
                history[-1] = {
                    "role": "assistant",
                    "content": "🌐 AI 服务暂时不可用，请稍后重试。您可以先上传文件进行规则分析。",
                }
                yield history
            except Exception as e:
                logger_manager.error(f"对话处理异常: {e}", exc_info=True)
                history[-1] = {"role": "assistant", "content": "⚠️ 对话处理出错，请稍后重试。"}
                yield history
            return

        # 无 LLM 时的规则回复
        reply = _quick_reply(message) or "收到您的消息。请上传需要审查的法律文件，我将为您进行自动化风险分析。"
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        yield history

    return chat_respond


# ============================================
# 人工修正反馈
# ============================================


def load_risk_options() -> list:
    """加载当前会话的风险列表供反馈选择"""
    session_id = review_store.latest_session_id
    if not session_id:
        return [("暂无风险", 0)]

    risks = review_store.get_risks(session_id)
    choices = []
    for i, risk in enumerate(risks, 1):
        label = f"风险{i}: {risk.get('name', '')} [{risk.get('risk_level', '')}]"
        choices.append((label, i))
    return choices if choices else [("暂无风险", 0)]


def submit_feedback(risk_idx, action, comment, corrected_level) -> str:
    """提交修正反馈"""
    if risk_idx == 0:
        return "⚠️ 请先选择风险项"

    session_id = review_store.latest_session_id
    if not session_id:
        return "⚠️ 请先进行文件审查"

    risks = review_store.get_risks(session_id)
    clauses = review_store.get_clauses(session_id)

    if not risks or risk_idx > len(risks):
        return "⚠️ 风险项不存在"

    risk = risks[risk_idx - 1]
    clause_id = risk.get("clause_id", 0)
    clause_text = ""
    clause_title = ""
    for c in clauses:
        if c.get("id") == clause_id:
            clause_text = c.get("content", "")
            clause_title = c.get("title", "")
            break

    session_data = review_store.get(session_id)

    try:
        from src.feedback_store import get_feedback_store

        store = get_feedback_store()
        store.record_correction(
            clause_id=clause_id,
            clause_text=clause_text,
            clause_title=clause_title,
            document_type=session_data.get("document_type", ""),
            playbook_id=session_data.get("playbook_id", ""),
            original_risk={
                "name": risk.get("name", ""),
                "risk_level": risk.get("risk_level", ""),
                "rule_id": risk.get("rule_id", ""),
            },
            user_action=action,
            user_comment=comment,
            corrected_level=corrected_level if action in ("level_down", "level_up", "missed_risk") else None,
        )
        return "✅ 修正已记录！Agent 下次遇到相似条款时会参考此反馈。"
    except Exception as e:
        return f"❌ 记录失败: {str(e)}"


def show_feedback_stats() -> str:
    """显示反馈统计"""
    try:
        from src.feedback_store import get_feedback_store

        store = get_feedback_store()
        stats = store.get_stats()
        lines = ["### 📊 反馈统计"]
        lines.append(f"总修正记录: **{stats['total_records']}**")
        lines.append(f"误报率: **{stats['false_positive_rate']:.1%}**")
        lines.append("\n**按操作类型**: ")
        for action, count in stats.get("by_action", {}).items():
            lines.append(f"- {action}: {count}")
        lines.append("\n**按风险类型**: ")
        for risk_name, count in stats.get("by_risk_type", {}).items():
            lines.append(f"- {risk_name}: {count}")
        return "\n".join(lines)
    except Exception as e:
        return f"统计加载失败: {str(e)}"


# ============================================
# 法规搜索
# ============================================


def make_search_handler(legal_matcher):
    """工厂函数：生成法规搜索处理器"""

    def search_laws(keyword: str) -> str:
        if not keyword:
            return "请输入搜索关键词"

        results = legal_matcher.search_by_keyword(keyword)
        if not results:
            return f"未找到与「{keyword}」相关的法条"

        output = f"### 🔍 与「{keyword}」相关的法条（共 {len(results)} 条）\n\n"
        for i, p in enumerate(results, 1):
            output += f"""
**{i}. 《{p.law}》{p.article}（{p.title}）**

{p.content[:200]}...

> 分类: {p.category} | 关键词: {", ".join(p.keywords)}

---
"""
        return output

    return search_laws
