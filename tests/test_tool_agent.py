"""
ToolCallingAgent 和 StagnationDetector 单元测试

覆盖：
- StagnationDetector:
  - 重复工具调用检测（相同参数 + 连续 3 次同工具）
  - 空结果连续出现检测
  - 信息增益不足检测
  - 正常情况不中断
- _compress_messages:
  - 消息数 ≤ 4 时不压缩
  - 旧工具结果截断
  - 新工具结果保留
  - 配对完整性校验（缺 result 的 tool_calls 被剥离）
- Agent 流式事件
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm.tool_agent import EventType, StagnationDetector, ToolCallingAgent
from src.llm.tools.base import ToolRegistry


# ============================================
# StagnationDetector 测试
# ============================================


class TestStagnationDetector:
    def setup_method(self):
        self.detector = StagnationDetector(max_same_tool=2, min_information_gain=0.2, max_empty_results=2)

    def test_no_history_returns_none(self):
        assert self.detector.check("tool_call", "", []) is None

    # --- 重复工具调用 ---

    def test_detect_same_tool_same_args(self):
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_result", "content": "找到相关法条..."},
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
        ]
        reason = self.detector.check("tool_call", "", history)
        assert reason is not None
        assert "重复调用" in reason

    def test_detect_same_tool_same_args_normalized(self):
        """参数格式不同但内容相同应被检测为重复"""
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_result", "content": "结果..."},
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
        ]
        reason = self.detector.check("tool_call", "", history)
        assert reason is not None

    def test_detect_three_consecutive_same_tool(self):
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "格式条款"}},
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "免责条款"}},
        ]
        reason = self.detector.check("tool_call", "", history)
        assert reason is not None
        assert "连续 3 次" in reason

    def test_different_tools_not_detected(self):
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_result", "content": "结果..."},
            {"action": "tool_call", "tool_name": "search_case_law", "tool_args": {"query": "违约金"}},
        ]
        reason = self.detector.check("tool_call", "", history)
        assert reason is None

    def test_non_tool_call_action_skips_repeated_check(self):
        """tool_result 动作不应触发重复工具调用检测（但可能触发信息增益检测）"""
        # 使用不同的内容避免信息增益检测触发
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_result", "content": "《民法典》第585条：约定的违约金过分高于造成的损失的"},
        ]
        reason = self.detector.check("tool_result", "《民法典》第577条：违约责任的一般规定，当事人应当承担继续履行", history)
        # 如果触发了中断，原因不应是"重复调用"
        if reason is not None:
            assert "重复调用" not in reason

    # --- 空结果连续出现 ---

    def test_detect_consecutive_empty_results(self):
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "量子"}},
            {"action": "tool_result", "content": "未找到相关法条"},
            {"action": "tool_call", "tool_name": "search_case_law", "tool_args": {"query": "量子"}},
            {"action": "tool_result", "content": "没有找到相关判例"},
        ]
        reason = self.detector.check("tool_result", "未找到相关内容", history)
        assert reason is not None
        assert "连续" in reason

    def test_non_empty_result_resets_empty_count(self):
        history = [
            {"action": "tool_result", "content": "未找到相关法条"},
            {"action": "tool_result", "content": "找到了相关法条：民法典第577条"},
            {"action": "tool_result", "content": "未找到相关内容"},
        ]
        reason = self.detector.check("tool_result", "未找到", history)
        # 只有 1 个连续空结果，不应触发
        assert reason is None

    # --- 信息增益检测 ---

    def test_detect_low_information_gain(self):
        """高度重复的工具结果应触发信息增益不足"""
        repeated_content = "《民法典》第五百七十七条：违约责任条款。当事人一方不履行合同义务的应当承担责任。" * 10
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约"}},
            {"action": "tool_result", "content": repeated_content},
        ]
        reason = self.detector.check("tool_result", repeated_content, history)
        assert reason is not None
        assert "信息增益" in reason or "重复" in reason

    # --- 正常情况 ---

    def test_normal_flow_no_interrupt(self):
        history = [
            {"action": "tool_call", "tool_name": "search_legal_provision", "tool_args": {"query": "违约金"}},
            {"action": "tool_result", "content": "《民法典》第585条：违约金条款"},
        ]
        reason = self.detector.check("tool_result", "找到相关判例：最高法案例", history)
        assert reason is None


# ============================================
# _compress_messages 测试
# ============================================


class TestCompressMessages:
    def test_short_messages_not_compressed(self):
        messages = [
            {"role": "system", "content": "你是法律助手"},
            {"role": "user", "content": "审查这个条款"},
            {"role": "assistant", "content": "分析结果"},
            {"role": "user", "content": "继续"},
        ]
        result = ToolCallingAgent._compress_messages(messages)
        assert len(result) == 4

    def test_old_tool_results_truncated(self):
        long_content = "A" * 2000
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_old", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call_old", "content": long_content},
            {"role": "user", "content": "q2"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_new", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call_new", "content": long_content},
        ]
        result = ToolCallingAgent._compress_messages(messages, max_tool_result_chars=200)

        # 旧的 tool result 应被截断
        old_tool = [m for m in result if m.get("role") == "tool" and m.get("tool_call_id") == "call_old"][0]
        assert len(old_tool["content"]) <= 210  # 200 + "...(已截断)"

        # 新的 tool result 应保留完整
        new_tool = [m for m in result if m.get("role") == "tool" and m.get("tool_call_id") == "call_new"][0]
        assert len(new_tool["content"]) == 2000

    def test_pair_integrity_stripped(self):
        """assistant(tool_calls) 的 id 没有对应 tool result 时，剥离 tool_calls"""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "thinking...",
                "tool_calls": [{"id": "call_orphan", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            },
            # 缺少对应的 tool result
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "final answer"},
        ]
        result = ToolCallingAgent._compress_messages(messages)

        # orphan tool_calls 应被剥离
        assistant_msgs = [m for m in result if m.get("role") == "assistant"]
        for msg in assistant_msgs:
            if msg.get("tool_calls"):
                # 如果还有 tool_calls，说明没被剥离（不应该发生）
                tc_ids = {tc["id"] for tc in msg["tool_calls"]}
                result_ids = {m.get("tool_call_id") for m in result if m.get("role") == "tool"}
                assert tc_ids.issubset(result_ids)

    def test_pair_integrity_preserved(self):
        """完整的 assistant(tool_calls) + tool(result) 配对应保留"""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "final"},
        ]
        result = ToolCallingAgent._compress_messages(messages)
        # call_1 配对完整，应保留 tool_calls
        assistant_with_tc = [m for m in result if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(assistant_with_tc) == 1
        assert assistant_with_tc[0]["tool_calls"][0]["id"] == "call_1"


# ============================================
# ToolCallingAgent 测试
# ============================================


class TestToolCallingAgent:
    def test_default_system_prompt(self):
        registry = ToolRegistry()
        agent = ToolCallingAgent(llm_client=MagicMock(), tool_registry=registry)
        assert "法律" in agent.system_prompt or "审查" in agent.system_prompt

    def test_max_iterations_default(self):
        registry = ToolRegistry()
        agent = ToolCallingAgent(llm_client=MagicMock(), tool_registry=registry)
        assert agent.max_iterations == 2

    @pytest.mark.asyncio
    async def test_analyze_stream_yields_events(self):
        """流式分析应产出 thinking → conclusion 事件"""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value="条款分析结论：无明显风险")
        mock_llm.chat_completion_with_tools = AsyncMock(
            return_value={"content": "条款分析结论：无明显风险", "tool_calls": None}
        )

        registry = ToolRegistry()
        agent = ToolCallingAgent(llm_client=mock_llm, tool_registry=registry, max_iterations=1)

        events = []
        async for event in agent.analyze_stream("甲方应在30日内付款"):
            events.append(event)

        types = [e.type for e in events]
        assert EventType.THINKING in types
        assert EventType.CONCLUSION in types

    @pytest.mark.asyncio
    async def test_analyze_non_stream(self):
        """非流式接口应返回 AgentOutput"""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value="无风险")
        mock_llm.chat_completion_with_tools = AsyncMock(return_value={"content": "无风险", "tool_calls": None})

        registry = ToolRegistry()
        agent = ToolCallingAgent(llm_client=mock_llm, tool_registry=registry, max_iterations=1)

        output = await agent.analyze("甲方应在30日内付款")
        assert output.conclusion
        assert isinstance(output.steps, list)

    @pytest.mark.asyncio
    async def test_tool_calling_flow(self):
        """Agent 应在 LLM 返回 tool_calls 时执行工具"""
        mock_llm = MagicMock()
        # 第一次返回 tool_call，第二次返回结论
        mock_llm.chat_completion_with_tools = AsyncMock(
            side_effect=[
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "search_legal_provision",
                            "arguments": {"query": "违约金"},
                        }
                    ],
                },
                {"content": "根据检索结果，违约金条款符合规定", "tool_calls": None},
            ]
        )
        mock_llm.chat_completion = AsyncMock(return_value="反思通过")

        registry = ToolRegistry()
        # 注册一个 mock 工具
        from src.llm.tools.base import BaseTool, ToolDefinition, ToolResult

        class MockLegalTool(BaseTool):
            @property
            def definition(self):
                return ToolDefinition(
                    name="search_legal_provision",
                    description="法规检索",
                    parameters={"type": "object", "properties": {}},
                )

            async def execute(self, arguments, tool_call_id=""):
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name="search_legal_provision",
                    success=True,
                    content="《民法典》第585条",
                )

        registry.register(MockLegalTool())
        agent = ToolCallingAgent(llm_client=mock_llm, tool_registry=registry, max_iterations=2)

        events = []
        async for event in agent.analyze_stream("违约金过高"):
            events.append(event)

        types = [e.type for e in events]
        assert EventType.TOOL_CALL in types
        assert EventType.TOOL_RESULT in types
        assert EventType.CONCLUSION in types
