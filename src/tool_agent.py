"""
Tool-Calling Agent 主循环（v2.2）
- ReAct 模式：推理 → 工具调用 → 执行 → 观察 → 继续推理
- 强制中断机制：检测重复调用、信息增益不足、空结果、推理收敛
- 异步流式输出：每步实时推送状态到前端
- 自我反思：结论输出前验证法条/判例引用准确性，修正幻觉引用
"""

import uuid as _uuid
import json
from typing import Dict, List, Optional, Any, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

from src.tools.base import ToolRegistry, ToolCall
from src.logger import logger_manager
from src.utils import text_similarity


# ============================================
# 流式事件定义
# ============================================

class EventType(Enum):
    THINKING = "thinking"           # 正在思考
    TOOL_CALL = "tool_call"         # 调用工具
    TOOL_RESULT = "tool_result"     # 工具返回
    REFLECTION = "reflection"       # 自我反思
    CONCLUSION = "conclusion"       # 最终结论
    INTERRUPTED = "interrupted"     # 强制中断
    ERROR = "error"                 # 错误


@dataclass
class AgentStreamEvent:
    """Agent 流式事件"""
    type: EventType
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict] = None
    step_number: int = 0
    is_final: bool = False  # 是否是最终结论


# ============================================
# 停滞检测器
# ============================================

class StagnationDetector:
    """
    智能停滞检测器

    检测以下 4 种情况并强制中断：
    1. 重复工具调用 — 连续调用同一工具 + 相同关键词
    2. 信息增益不足 — 新结果与已有结果高度重复
    3. 空结果连续出现 — 工具返回"未找到"且 LLM 仍要调用
    4. 推理收敛 — LLM 结论与上轮无明显变化
    """

    def __init__(
        self,
        max_same_tool: int = 2,
        min_information_gain: float = 0.2,
        max_empty_results: int = 2
    ):
        self.max_same_tool = max_same_tool
        self.min_information_gain = min_information_gain
        self.max_empty_results = max_empty_results

    def check(
        self,
        current_action: str,
        current_content: str,
        history: List[Dict]
    ) -> Optional[str]:
        """
        检测是否应该中断

        Args:
            current_action: 当前动作 (tool_call/conclusion)
            current_content: 当前内容
            history: 历史步骤记录

        Returns:
            中断原因，None 表示继续
        """
        if not history:
            return None

        # 1. 重复工具调用检测
        reason = self._detect_repeated_tools(current_action, history)
        if reason:
            return reason

        # 2. 空结果连续出现检测
        reason = self._detect_empty_results(current_content, history)
        if reason:
            return reason

        # 3. 信息增益检测（仅对工具调用结果）
        if current_action == "tool_result":
            reason = self._detect_low_information_gain(current_content, history)
            if reason:
                return reason

        return None

    def _detect_repeated_tools(self, current_action: str, history: List[Dict]) -> Optional[str]:
        """检测重复工具调用"""
        if current_action != "tool_call":
            return None

        # 获取最近的工具调用
        recent_calls = [
            h for h in history[-4:]
            if h.get("action") == "tool_call"
        ]

        if len(recent_calls) < 2:
            return None

        # 检查是否同一工具 + 相同参数（归一化比较）
        last = recent_calls[-1]
        second_last = recent_calls[-2]

        if (last.get("tool_name") == second_last.get("tool_name") and
            self._normalize_args(last.get("tool_args")) == self._normalize_args(second_last.get("tool_args"))):
            return (
                f"检测到重复调用同一工具「{last.get('tool_name')}」"
                f"（相同参数），无新信息可获取，强制中断"
            )

        # 检查最近 3 次是否都是同一工具（即使参数不同）
        if len(recent_calls) >= 3:
            tools = [c.get("tool_name") for c in recent_calls[-3:]]
            if len(set(tools)) == 1:
                return (
                    f"连续 3 次调用同一工具「{tools[0]}」，"
                    f"可能已穷尽该工具信息，强制中断"
                )

        return None

    @staticmethod
    def _normalize_args(args: Any) -> str:
        """归一化工具参数用于比较，消除 LLM 输出的格式差异"""
        if not args:
            return ""
        if isinstance(args, str):
            return args.strip().lower()
        try:
            return json.dumps(args, sort_keys=True, ensure_ascii=False).lower()
        except (TypeError, ValueError):
            return str(args).strip().lower()

    def _detect_empty_results(self, current_content: str, history: List[Dict]) -> Optional[str]:
        """检测空结果连续出现"""
        empty_indicators = [
            "未找到", "没有找到", "不存在", "无相关",
            "not found", "no results", "无匹配"
        ]

        is_empty = any(ind in current_content for ind in empty_indicators)
        if not is_empty:
            return None

        # 统计连续空结果
        consecutive_empty = 0
        for h in reversed(history):
            if h.get("action") == "tool_result":
                content = h.get("content", "")
                if any(ind in content for ind in empty_indicators):
                    consecutive_empty += 1
                else:
                    break

        if consecutive_empty >= self.max_empty_results:
            return (
                f"连续 {consecutive_empty} 次工具检索未找到结果，"
                f"该领域可能缺乏相关法规/判例，强制中断"
            )

        return None

    def _detect_low_information_gain(
        self,
        current_content: str,
        history: List[Dict]
    ) -> Optional[str]:
        """检测信息增益不足"""
        # 获取上一轮工具结果
        prev_results = [
            h.get("content", "")
            for h in history[-4:]
            if h.get("action") == "tool_result"
        ]

        if not prev_results:
            return None

        # 计算与已有结果的最大相似度
        max_similarity = 0.0
        for prev in prev_results:
            similarity = text_similarity(current_content, prev, max_chars=2000)
            max_similarity = max(max_similarity, similarity)

        if max_similarity > (1 - self.min_information_gain):
            return (
                f"新检索结果与已有内容高度重复（相似度 {max_similarity:.0%}），"
                f"信息增益不足，强制中断"
            )

        return None


# ============================================
# Agent 主循环
# ============================================

class ToolCallingAgent:
    """
    Tool-Calling Agent (v2.2)

    增强：
    - 强制中断机制（4 维度停滞检测）
    - 异步流式输出（async generator）
    """

    def __init__(
        self,
        llm_client,
        tool_registry: ToolRegistry,
        max_iterations: int = 2,
        system_prompt: Optional[str] = None,
        enable_streaming: bool = True
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.enable_streaming = enable_streaming
        self.logger = logger_manager
        self.stagnation_detector = StagnationDetector()

        self.system_prompt = system_prompt or self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        tool_names = ", ".join(t.name for t in self.tool_registry.list_tools())

        return f"""你是专业法律审查 Agent，擅长中国法律风险分析。

## 可用工具
{tool_names}

## 工具使用规则
- 需要检索法规条文或司法判例时调用相关工具，每次只调用一个工具
- 工具返回结果后，基于结果继续分析；如果未找到相关内容或结果与已有信息重复，停止调用
- 不确定的判断必须标注"⚠️ AI推测（无直接法规支撑）"

## 引用规范
- 引用法条时注明完整法律名称和条款号（如"《民法典》第506条"）
- 引用判例时注明案号（如"（2023）最高法民终xxx号"）
- 不得编造不存在的法条或判例

## 输出要求
- 条理清晰，风险等级明确（严重/高/中/低）
- 每个风险点附法律依据和修改建议"""

    # ===== 流式接口 =====

    async def analyze_stream(
        self,
        clause_text: str,
        context: str = "",
        role_context: str = ""
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """
        分析条款（流式输出）

        Yields:
            AgentStreamEvent: 每步状态事件
        """
        history: List[Dict] = []

        # 注入历史修正（反馈闭环）
        feedback_context = ""
        try:
            from src.feedback_store import get_feedback_store
            store = get_feedback_store()
            feedback_context = store.export_as_few_shot(clause_text)
        except Exception:
            pass

        system_prompt = self.system_prompt
        if feedback_context:
            system_prompt = self.system_prompt + "\n\n" + feedback_context

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"请审查以下法律条款：\n\n"
                    f"**条款内容**：\n{clause_text}\n\n"
                    f"{f'**合同上下文**：\n{context}\n\n' if context else ''}"
                    f"{f'**审查立场**：{role_context}\n\n' if role_context else ''}"
                    f"请分析该条款的合法性、潜在风险，并在需要时调用工具检索法规或判例来支撑你的判断。"
                )
            }
        ]

        self.logger.info(f"Agent 开始流式分析条款: {clause_text[:50]}...")

        # 首轮思考
        yield AgentStreamEvent(
            type=EventType.THINKING,
            content="🔍 正在分析条款内容...",
            step_number=0
        )

        for iteration in range(1, self.max_iterations + 1):
            step_prefix = f"第{iteration}轮"

            # 压缩历史上下文，控制 token 消耗
            messages = self._compress_messages(messages)

            # LLM 调用前 yield 思考状态
            yield AgentStreamEvent(
                type=EventType.THINKING,
                content=f"🤔 {step_prefix}：AI 正在分析...",
                step_number=iteration
            )

            response = await self._llm_call(messages)

            if response.get("tool_calls"):
                tool_calls = response["tool_calls"]

                # 追加 assistant 消息（含 tool_calls），保持 OpenAI 消息序列完整性
                assistant_tc_payload = []
                for tc in tool_calls:
                    args = tc.get("arguments", {})
                    assistant_tc_payload.append({
                        "id": tc.get("id") or f"call_{_uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
                        }
                    })
                messages.append({
                    "role": "assistant",
                    "content": response.get("content"),
                    "tool_calls": assistant_tc_payload
                })

                for idx, tc in enumerate(tool_calls):
                    tc_id = assistant_tc_payload[idx]["id"]

                    # 停滞检测 — 工具调用前
                    history.append({
                        "action": "tool_call",
                        "tool_name": tc["name"],
                        "tool_args": tc.get("arguments", {})
                    })

                    stop_reason = self.stagnation_detector.check(
                        "tool_call", "", history
                    )
                    if stop_reason:
                        self.logger.warning(f"Agent 强制中断: {stop_reason}")
                        yield AgentStreamEvent(
                            type=EventType.INTERRUPTED,
                            content=f"🛑 {stop_reason}",
                            step_number=iteration,
                            is_final=True
                        )
                        # 基于已有信息生成结论
                        conclusion = await self._generate_fallback_conclusion(messages)
                        yield AgentStreamEvent(
                            type=EventType.CONCLUSION,
                            content=conclusion,
                            step_number=iteration,
                            is_final=True
                        )
                        return

                    # yield 工具调用状态
                    yield AgentStreamEvent(
                        type=EventType.TOOL_CALL,
                        content=f"📡 {step_prefix}：调用 {tc['name']}",
                        tool_name=tc["name"],
                        tool_args=tc.get("arguments", {}),
                        step_number=iteration
                    )

                    # 执行工具
                    result = await self.tool_registry.execute(ToolCall(
                        id=tc_id,
                        name=tc["name"],
                        arguments=tc.get("arguments", {})
                    ))

                    # yield 工具结果
                    result_preview = result.content[:200] + (
                        "..." if len(result.content) > 200 else ""
                    )
                    yield AgentStreamEvent(
                        type=EventType.TOOL_RESULT,
                        content=f"✅ {step_prefix}：{tc['name']} 返回结果 — {result_preview}",
                        tool_name=tc["name"],
                        step_number=iteration
                    )

                    # 停滞检测 — 工具结果后
                    history.append({
                        "action": "tool_result",
                        "tool_name": tc["name"],
                        "content": result.content
                    })

                    stop_reason = self.stagnation_detector.check(
                        "tool_result", result.content, history
                    )
                    if stop_reason:
                        self.logger.warning(f"Agent 强制中断: {stop_reason}")
                        yield AgentStreamEvent(
                            type=EventType.INTERRUPTED,
                            content=f"🛑 {stop_reason}",
                            step_number=iteration,
                            is_final=True
                        )
                        # 生成草案 → 自我反思
                        draft = await self._generate_fallback_conclusion(messages)
                        verified = await self._self_reflect_and_finalize(
                            draft, messages, history, iteration
                        )
                        yield AgentStreamEvent(
                            type=EventType.REFLECTION,
                            content=verified["reflection_summary"],
                            step_number=iteration
                        )
                        yield AgentStreamEvent(
                            type=EventType.CONCLUSION,
                            content=verified["final_conclusion"],
                            step_number=iteration,
                            is_final=True
                        )
                        return

                    # 将工具结果加入对话
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result.content
                    })

            elif response.get("content"):
                # LLM 给出草案结论 → 进入自我反思
                draft_conclusion = response["content"]

                verified_conclusion = await self._self_reflect_and_finalize(
                    draft_conclusion, messages, history, iteration
                )

                # yield 反思事件
                yield AgentStreamEvent(
                    type=EventType.REFLECTION,
                    content=verified_conclusion["reflection_summary"],
                    step_number=iteration
                )

                # yield 最终结论
                yield AgentStreamEvent(
                    type=EventType.CONCLUSION,
                    content=verified_conclusion["final_conclusion"],
                    step_number=iteration,
                    is_final=True
                )

                self.logger.info(
                    f"Agent 分析完成: {iteration} 轮, "
                    f"工具调用 {sum(1 for h in history if h['action'] == 'tool_call')} 次, "
                    f"反思={'通过' if verified_conclusion['reflection_passed'] else '修正'}"
                )
                return

        # 达到最大迭代次数
        self.logger.warning(f"Agent 达到最大迭代次数 ({self.max_iterations})")
        yield AgentStreamEvent(
            type=EventType.INTERRUPTED,
            content=f"🛑 已达到最大迭代次数 ({self.max_iterations})，进入反思验证",
            step_number=self.max_iterations,
            is_final=True
        )
        draft = await self._generate_fallback_conclusion(messages)
        verified = await self._self_reflect_and_finalize(
            draft, messages, history, self.max_iterations
        )
        yield AgentStreamEvent(
            type=EventType.REFLECTION,
            content=verified["reflection_summary"],
            step_number=self.max_iterations
        )
        yield AgentStreamEvent(
            type=EventType.CONCLUSION,
            content=verified["final_conclusion"],
            step_number=self.max_iterations,
            is_final=True
        )

    # ===== 非流式接口（向后兼容） =====

    async def analyze(
        self,
        clause_text: str,
        context: str = "",
        role_context: str = ""
    ) -> "AgentOutput":
        """
        分析条款（非流式，向后兼容）
        内部使用流式接口，收集所有事件后返回
        """
        steps = []
        conclusion = ""
        tools_used = 0

        async for event in self.analyze_stream(clause_text, context, role_context):
            if event.type == EventType.CONCLUSION and event.is_final:
                conclusion = event.content
            elif event.type == EventType.REFLECTION:
                steps.append({
                    "step_number": event.step_number,
                    "action": "reflection",
                    "content": event.content
                })
            elif event.type == EventType.TOOL_CALL:
                tools_used += 1
                steps.append({
                    "step_number": event.step_number,
                    "action": "tool_call",
                    "content": event.content,
                    "tool_name": event.tool_name
                })
            elif event.type == EventType.THINKING:
                steps.append({
                    "step_number": event.step_number,
                    "action": "thinking",
                    "content": event.content
                })

        return AgentOutput(
            conclusion=conclusion,
            steps=steps,
            tools_used=tools_used
        )

    async def _generate_fallback_conclusion(self, messages: List[Dict]) -> str:
        """
        基于已有对话历史生成结论（不使用工具）

        当强制中断时调用
        """
        try:
            messages = self._compress_messages(messages, max_tool_result_chars=300)
            messages.append({
                "role": "user",
                "content": "基于以上信息给出最终审查结论。无法规支撑时基于法律知识分析，不确定标注'AI推测'。"
            })

            response = await self.llm_client.chat_completion(
                prompt="",
                messages=messages,
                temperature=0.1,
                max_tokens=2000
            )
            return response
        except Exception as e:
            return f"⚠️ 审查中断，无法生成完整结论。原因：{str(e)}。建议人工复核。"

    async def _self_reflect_and_finalize(
        self,
        draft_conclusion: str,
        messages: List[Dict],
        history: List[Dict],
        iteration: int
    ) -> Dict:
        """
        自我反思：验证结论中的法条/判例引用是否准确

        将草案结论与工具检索结果交叉核对，修正幻觉引用。

        Args:
            draft_conclusion: LLM 生成的草案结论
            messages: 完整对话历史
            history: 工具调用历史
            iteration: 当前迭代轮次

        Returns:
            {
                "final_conclusion": str,       # 最终结论（可能已修正）
                "reflection_summary": str,     # 反思摘要
                "reflection_passed": bool,     # 是否通过验证
                "corrections_made": int        # 修正数量
            }
        """
        # 提取工具结果（用于交叉核对的事实依据），截断控制 token
        tool_results_text = ""
        for h in history:
            if h.get("action") == "tool_result":
                content = h.get('content', '')
                if len(content) > 800:
                    content = content[:800] + "...(已截断)"
                tool_results_text += f"[{h.get('tool_name', 'unknown')}]: {content}\n\n"

        if not tool_results_text.strip():
            # 没有工具结果可核对，直接返回草案
            return {
                "final_conclusion": draft_conclusion,
                "reflection_summary": "🔍 未使用工具检索，跳过法条验证",
                "reflection_passed": True,
                "corrections_made": 0
            }

        reflection_prompt = f"""核查以下审查结论的引用准确性。

## 工具检索结果
{tool_results_text}

## 草案结论
{draft_conclusion}

核查要点：法条/判例引用是否与工具结果一致，是否有过度推断或遗漏，引用法条是否仍有效（注意《担保法》《合同法》等已被《民法典》取代）。

返回 JSON：{{"reflection_passed":bool,"corrections_made":int,"reflection_summary":"≤50字","final_conclusion":"修正后结论或原结论","timeliness_warning":str|null}}"""

        try:
            response = await self.llm_client.chat_completion(
                reflection_prompt,
                system_prompt="法律审查质量核查。仅返回 JSON。",
                temperature=0.1,
                max_tokens=1000
            )

            # 用 raw_decode 从第一个 '{' 开始解析，避免贪婪匹配错误范围
            idx = response.find('{')
            if idx != -1:
                decoder = json.JSONDecoder()
                result_data, _ = decoder.raw_decode(response, idx)

                # 提取结果
                final = result_data.get("final_conclusion", draft_conclusion)
                passed = result_data.get("reflection_passed", False)
                summary = result_data.get("reflection_summary", "反思完成")
                corrections = result_data.get("corrections_made", 0)

                # 如果反射未通过但 corrections=0，说明 LLM 没修正
                if not passed and corrections == 0:
                    final = draft_conclusion
                    summary = "⚠️ 反思发现引用存疑，但未能自动修正，建议人工核实"

                self.logger.info(
                    f"自我反思: passed={passed}, corrections={corrections}, summary={summary}"
                )

                return {
                    "final_conclusion": final,
                    "reflection_summary": f"{'✅' if passed else '⚠️'} {summary}",
                    "reflection_passed": passed,
                    "corrections_made": corrections
                }

            # JSON 解析失败，返回草案
            return {
                "final_conclusion": draft_conclusion,
                "reflection_summary": "⚠️ 反思结果解析失败，使用草案结论",
                "reflection_passed": False,
                "corrections_made": 0
            }

        except Exception as e:
            self.logger.error(f"自我反思失败: {e}")
            return {
                "final_conclusion": draft_conclusion,
                "reflection_summary": f"⚠️ 反思步骤异常：{str(e)}，使用草案结论",
                "reflection_passed": False,
                "corrections_made": 0
            }

    async def _llm_call(self, messages: List[Dict]) -> Dict:
        try:
            tool_schemas = self.tool_registry.get_openai_schemas()

            response = await self.llm_client.chat_completion_with_tools(
                messages=messages,
                tools=tool_schemas,
                temperature=0.1,
                max_tokens=2000
            )

            return response

        except Exception as e:
            self.logger.error(f"LLM 调用失败: {e}")
            return {"content": f"AI 分析暂时不可用：{str(e)}"}

    @staticmethod
    def _compress_messages(messages: List[Dict], max_tool_result_chars: int = 800) -> List[Dict]:
        """
        压缩消息历史，截断旧的工具结果以控制上下文长度

        保留 system prompt 和最新一轮的工具结果完整，
        对更早的工具结果只保留摘要。
        严格保持 assistant(tool_calls) + tool(result) 配对完整性。
        """
        if len(messages) <= 4:
            return messages

        compressed = []
        max_user_content_chars = 5000

        # 识别最新一轮工具调用的 tool_call_id 集合
        # 从末尾向前扫描，收集最后一组连续 tool 消息的 id
        latest_tool_ids = set()
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id:
                    latest_tool_ids.add(tc_id)
            else:
                if latest_tool_ids:
                    break

        seen_tool_results = 0
        for i, msg in enumerate(messages):
            role = msg.get("role", "")

            if role == "system":
                compressed.append(msg)

            elif role == "assistant" and msg.get("tool_calls"):
                # assistant 消息含 tool_calls：检查其 tool_calls 中的 id 是否都在最新一轮
                tc_ids = {tc.get("id", "") for tc in msg["tool_calls"]}
                is_latest_round = tc_ids & latest_tool_ids
                if not is_latest_round:
                    # 旧轮次的 assistant+tool_calls，保留结构但截断 content
                    content = msg.get("content") or ""
                    if len(content) > max_user_content_chars:
                        msg = {**msg, "content": content[:max_user_content_chars] + "...(已截断)"}
                compressed.append(msg)

            elif role == "tool":
                seen_tool_results += 1
                tc_id = msg.get("tool_call_id", "")
                if tc_id in latest_tool_ids:
                    # 最新一轮工具结果，完整保留
                    compressed.append(msg)
                else:
                    # 旧的工具结果：截断
                    content = msg.get("content", "")
                    if len(content) > max_tool_result_chars:
                        compressed.append({
                            **msg,
                            "content": content[:max_tool_result_chars] + "...(已截断)"
                        })
                    else:
                        compressed.append(msg)

            else:
                # user/assistant（无 tool_calls）消息
                is_last_two = (i >= len(messages) - 2)
                content = msg.get("content", "")
                if not is_last_two and len(content) > max_user_content_chars:
                    compressed.append({
                        **msg,
                        "content": content[:max_user_content_chars] + "...(已截断)"
                    })
                else:
                    compressed.append(msg)

        return compressed


# ===== 向后兼容的数据结构 =====

@dataclass
class AgentStep:
    """Agent 单步执行记录（兼容旧版）"""
    step_number: int
    action: str
    content: str
    tool_name: Optional[str] = None
    tool_result: Optional[str] = None
    timestamp: float = 0.0


@dataclass
class AgentOutput:
    """Agent 最终输出（兼容旧版）"""
    conclusion: str
    steps: List[Dict] = field(default_factory=list)
    tools_used: int = 0
    max_iterations_reached: bool = False
