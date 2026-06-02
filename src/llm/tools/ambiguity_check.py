"""
歧义检测工具
- 检测条款是否存在歧义或模糊表述
- 由 LLM 执行语义分析
"""

from typing import Any

from src.infra.utils import extract_json_object
from src.llm.tools.base import BaseTool, ToolDefinition, ToolResult


class AmbiguityCheckTool(BaseTool):
    """歧义检测工具"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def set_llm_client(self, llm_client):
        """设置 LLM 客户端"""
        self.llm_client = llm_client

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_clause_ambiguity",
            description=(
                "检测法律条款是否存在歧义、模糊表述或多种解释可能。"
                "当你发现某个条款表述不清、可能有多种理解方式、"
                "或不确定条款的真实含义时，调用此工具。"
                "工具会分析条款的模糊点并给出澄清建议。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "clause_text": {"type": "string", "description": "待检测的条款完整文本"},
                    "context": {
                        "type": "string",
                        "description": ("可选的合同上下文，帮助理解条款含义。例如合同类型、双方角色、相关条款等"),
                    },
                },
                "required": ["clause_text"],
            },
        )

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        clause_text = arguments.get("clause_text", "")
        context = arguments.get("context", "")

        if not clause_text:
            return ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, success=False, content="错误：条款文本不能为空"
            )

        if not self.llm_client:
            return ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, success=False, content="错误：LLM 客户端未初始化"
            )

        prompt = self._build_prompt(clause_text, context)

        try:
            response = await self.llm_client.chat_completion(
                prompt,
                system_prompt="你是法律语言分析专家。仅返回 JSON，不要添加任何其他文字。",
                temperature=0.1,
                max_tokens=1000,
            )

            result_data = self._parse_json_response(response)
            if result_data is None:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    content="歧义分析结果解析失败：LLM 返回了无效的 JSON",
                )

            return self._format_result(tool_call_id, result_data)

        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, success=False, content=f"歧义检测失败: {str(e)}"
            )

    @staticmethod
    def _build_prompt(clause_text: str, context: str | None = None) -> str:
        """构建 LLM 提示词"""
        parts = [
            "请分析以下法律条款是否存在歧义，返回 JSON 格式结果。",
            "",
            "## 分析维度",
            "- 语义歧义：同一表述可有多种理解",
            "- 指代不明：代词或引用对象不清晰",
            "- 条件模糊：触发条件或边界不明确",
            "- 法律概念不确定：专业术语使用不当或含义模糊",
            "- 冲突风险：与其他条款或法律存在潜在冲突",
            "",
            "## 返回格式",
            "{",
            '  "has_ambiguity": true/false,',
            '  "overall_clarity": "清晰/基本清晰/存在歧义/严重歧义",',
            '  "summary": "不超过50字的总体评价",',
            '  "ambiguity_points": [',
            "    {",
            '      "type": "歧义类型",',
            '      "text": "歧义文本片段",',
            '      "explanation": "歧义说明",',
            '      "risk_level": "高/中/低",',
            '      "suggestion": "修改建议"',
            "    }",
            "  ]",
            "}",
            "",
            "## 待分析条款",
            clause_text,
        ]

        if context:
            parts.extend(["", "## 合同上下文", context])

        return "\n".join(parts)

    @staticmethod
    def _parse_json_response(response: str) -> dict | None:
        """解析 LLM 返回的 JSON（括号计数法，正确处理嵌套）"""
        import json

        raw = extract_json_object(response)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _format_result(tool_call_id: str, result_data: dict) -> ToolResult:
        """格式化输出结果"""
        has_ambiguity = result_data.get("has_ambiguity", False)
        clarity = result_data.get("overall_clarity", "未知")
        summary = result_data.get("summary", "")

        output_parts = [
            "🔍 歧义检测结果",
            f"**清晰度**: {clarity}",
            f"**评价**: {summary}",
        ]

        if has_ambiguity:
            points = result_data.get("ambiguity_points", [])
            if points:
                output_parts.append(f"\n**发现 {len(points)} 处歧义**：\n")
                for i, p in enumerate(points, 1):
                    output_parts.append(
                        f"**{i}. [{p.get('type', '未知')}]** {p.get('risk_level', '未知')}风险\n"
                        f"- 歧义文本：「{p.get('text', '')}」\n"
                        f"- 说明：{p.get('explanation', '')}\n"
                        f"- 建议：{p.get('suggestion', '')}"
                    )
            else:
                output_parts.append("\n⚠️ 检测到歧义但未提供详细信息")
        else:
            output_parts.append("\n✅ 未发现明显歧义")

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name="check_clause_ambiguity",
            success=True,
            content="\n\n".join(output_parts),
            metadata={"has_ambiguity": has_ambiguity, "clarity": clarity},
        )
