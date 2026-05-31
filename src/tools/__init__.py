"""
工具调用模块包
- 工具基类、工具注册表
- 法规检索、判例检索、歧义检测工具
"""

from .base import BaseTool, ToolDefinition, ToolCall, ToolResult, ToolRegistry
from .legal_search import LegalSearchTool
from .case_search import CaseSearchTool
from .ambiguity_check import AmbiguityCheckTool

__all__ = [
    "BaseTool",
    "ToolDefinition",
    "ToolCall",
    "ToolResult",
    "ToolRegistry",
    "LegalSearchTool",
    "CaseSearchTool",
    "AmbiguityCheckTool",
]
