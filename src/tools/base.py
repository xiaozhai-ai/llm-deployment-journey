"""
工具基类与注册表
- 定义统一的工具接口
- 管理工具的注册、发现和执行
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class ToolDefinition:
    """工具定义（OpenAI 兼容格式）"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 格式

    def to_openai_schema(self) -> Dict:
        """转换为 OpenAI Tool Schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


@dataclass
class ToolCall:
    """工具调用请求"""
    id: str  # 调用 ID（由 LLM 返回）
    name: str  # 工具名称
    arguments: Dict[str, Any]  # 参数


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_call_id: str
    tool_name: str
    success: bool
    content: str  # 返回给 LLM 的内容
    metadata: Dict = field(default_factory=dict)


class BaseTool(ABC):
    """工具基类"""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """工具定义"""
        pass

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], tool_call_id: str = "") -> ToolResult:
        """
        执行工具

        Args:
            arguments: 工具参数
            tool_call_id: 工具调用 ID（由 LLM 返回）

        Returns:
            ToolResult: 执行结果
        """
        pass

    @property
    def name(self) -> str:
        return self.definition.name


class ToolRegistry:
    """工具注册表"""

    DEFAULT_TIMEOUT = 30  # 默认工具执行超时（秒）

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self._tools: Dict[str, BaseTool] = {}
        self._timeout = timeout

    def register(self, tool: BaseTool):
        """注册工具"""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        """列出所有工具"""
        return list(self._tools.values())

    def get_openai_schemas(self) -> List[Dict]:
        """获取所有工具的 OpenAI Schema"""
        return [tool.definition.to_openai_schema() for tool in self._tools.values()]

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        执行工具调用（带超时控制）

        Args:
            tool_call: 工具调用请求

        Returns:
            ToolResult: 执行结果
        """
        tool = self.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                success=False,
                content=f"错误：工具 '{tool_call.name}' 不存在"
            )

        try:
            return await asyncio.wait_for(
                tool.execute(tool_call.arguments, tool_call.id),
                timeout=self._timeout
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                success=False,
                content=f"工具 '{tool_call.name}' 执行超时（{self._timeout}s）"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                success=False,
                content=f"工具执行失败: {str(e)}"
            )
