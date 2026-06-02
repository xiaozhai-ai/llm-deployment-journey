"""
ToolRegistry 和基类单元测试

覆盖：
- 工具注册/注销/查找
- OpenAI Schema 生成
- 超时控制
- 异常处理
- 未知工具执行
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm.tools.base import BaseTool, ToolCall, ToolDefinition, ToolRegistry, ToolResult


# ============================================
# 测试用 Mock 工具
# ============================================


class MockTool(BaseTool):
    """测试用简单工具"""

    def __init__(self, name: str = "mock_tool", description: str = "测试工具"):
        self._name = name
        self._description = description
        self.execute_mock = AsyncMock(
            return_value=ToolResult(tool_call_id="test", tool_name=name, success=True, content="ok")
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        return await self.execute_mock(arguments, tool_call_id)


class SlowTool(BaseTool):
    """模拟超时的工具"""

    def __init__(self, delay: float = 5.0):
        self.delay = delay

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(name="slow_tool", description="慢工具", parameters={"type": "object", "properties": {}})

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        await asyncio.sleep(self.delay)
        return ToolResult(tool_call_id=tool_call_id, tool_name="slow_tool", success=True, content="done")


class ErrorTool(BaseTool):
    """模拟异常的工具"""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="error_tool", description="异常工具", parameters={"type": "object", "properties": {}}
        )

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        raise ValueError("工具内部错误")


# ============================================
# ToolDefinition 测试
# ============================================


class TestToolDefinition:
    def test_to_openai_schema(self):
        td = ToolDefinition(
            name="test", description="desc", parameters={"type": "object", "properties": {"q": {"type": "string"}}}
        )
        schema = td.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test"
        assert schema["function"]["description"] == "desc"
        assert "properties" in schema["function"]["parameters"]


# ============================================
# ToolRegistry 测试
# ============================================


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = MockTool("my_tool")
        registry.register(tool)
        assert registry.get("my_tool") is tool

    def test_get_nonexistent_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister(self):
        registry = ToolRegistry()
        tool = MockTool("my_tool")
        registry.register(tool)
        assert registry.unregister("my_tool") is True
        assert registry.get("my_tool") is None

    def test_unregister_nonexistent(self):
        registry = ToolRegistry()
        assert registry.unregister("nonexistent") is False

    def test_list_tools(self):
        registry = ToolRegistry()
        t1 = MockTool("tool_a")
        t2 = MockTool("tool_b")
        registry.register(t1)
        registry.register(t2)
        tools = registry.list_tools()
        assert len(tools) == 2
        assert t1 in tools and t2 in tools

    def test_get_openai_schemas(self):
        registry = ToolRegistry()
        registry.register(MockTool("tool_a"))
        registry.register(MockTool("tool_b"))
        schemas = registry.get_openai_schemas()
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_execute_success(self):
        registry = ToolRegistry()
        tool = MockTool("my_tool")
        registry.register(tool)
        tc = ToolCall(id="call_1", name="my_tool", arguments={"query": "test"})
        result = await registry.execute(tc)
        assert result.success is True
        assert result.content == "ok"
        tool.execute_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        tc = ToolCall(id="call_1", name="nonexistent", arguments={})
        result = await registry.execute(tc)
        assert result.success is False
        assert "不存在" in result.content

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        registry = ToolRegistry(timeout=1)
        registry.register(SlowTool(delay=5.0))
        tc = ToolCall(id="call_1", name="slow_tool", arguments={})
        result = await registry.execute(tc)
        assert result.success is False
        assert "超时" in result.content

    @pytest.mark.asyncio
    async def test_execute_exception(self):
        registry = ToolRegistry()
        registry.register(ErrorTool())
        tc = ToolCall(id="call_1", name="error_tool", arguments={})
        result = await registry.execute(tc)
        assert result.success is False
        assert "工具内部错误" in result.content


# ============================================
# BaseTool.name 属性测试
# ============================================


class TestBaseToolName:
    def test_name_property(self):
        tool = MockTool("my_tool")
        assert tool.name == "my_tool"
