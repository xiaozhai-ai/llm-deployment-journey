"""
判例检索工具
- 检索相关司法判例/指导案例
- 数据来源：预置案例库（config/case_law.yaml）
"""

import os
from typing import Any

import yaml

from src.core.config import get_paths_config
from src.infra.utils import bigram_jaccard
from src.llm.tools.base import BaseTool, ToolDefinition, ToolResult


class CaseSearchTool(BaseTool):
    """判例检索工具"""

    def __init__(self, case_law_path: str | None = None, vector_store=None):
        self.cases: list[dict] = []
        self.vector_store = vector_store

        if case_law_path and os.path.exists(case_law_path):
            self._load_cases(case_law_path)
        else:
            # 从配置模块获取路径
            paths_config = get_paths_config()
            default_path = paths_config["case_law_path"]
            if default_path.exists():
                self._load_cases(str(default_path))

    def set_vector_store(self, vector_store):
        """设置向量存储（用于语义检索）"""
        self.vector_store = vector_store

    def _load_cases(self, path: str):
        """加载案例库"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.cases = data.get("cases", [])

    def add_case(self, case: dict):
        """动态添加案例"""
        self.cases.append(case)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_case_law",
            description=(
                "检索中国司法判例和指导案例。当你需要：\n"
                "1. 了解某类条款在司法实践中的裁判规则\n"
                "2. 查找支持或反驳某个法律观点的判例\n"
                "3. 确认某个法律争议的最高法院态度\n"
                "调用此工具。注意：案例库为预置典型案件，非实时数据库。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "案件关键词。例如：'对赌协议 业绩补偿'、'格式条款 提示义务'、'违约金 过高 调整'"
                        ),
                    },
                    "court_level": {
                        "type": "string",
                        "description": "可选的法院层级过滤",
                        "enum": ["最高人民法院", "高级人民法院", "中级人民法院", "基层人民法院"],
                    },
                    "case_type": {
                        "type": "string",
                        "description": "可选的案件类型",
                        "enum": ["指导案例", "典型案例", "公报案例", "一般判例"],
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        query = arguments.get("query", "")
        court_level = arguments.get("court_level")
        case_type = arguments.get("case_type")

        if not query:
            return ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, success=False, content="错误：检索关键词不能为空"
            )

        # 检索匹配的案例
        results = self._search_cases(query, court_level, case_type)

        if not results:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                content=(
                    f"未在预置案例库中找到与「{query}」直接匹配的判例。\n\n"
                    "建议：\n"
                    "1. 尝试调整检索关键词\n"
                    "2. 此领域可能缺乏指导性案例\n"
                    "3. 建议通过中国裁判文书网或专业数据库进一步检索\n\n"
                    "⚠️ 注意：本工具案例库为预置典型案例，非实时全量数据库。"
                ),
            )

        # 格式化结果
        output_parts = [f"⚖️ 判例检索结果（关键词：{query}）\n"]

        for i, case in enumerate(results, 1):
            output_parts.append(
                f"**{i}. {case.get('title', '未命名案例')}**\n"
                f"- **案号**: {case.get('case_number', '无')}\n"
                f"- **法院**: {case.get('court', '')}\n"
                f"- **类型**: {case.get('case_type', '')}\n"
                f"- **争议焦点**: {case.get('issue', '')}\n"
                f"- **裁判要旨**: {case.get('holding', '')}\n"
                f"- **关键词**: {', '.join(case.get('keywords', []))}"
            )

        output_parts.append(
            "\n> ⚠️ 以上案例来源于预置典型案例库，仅供审查参考，不构成法律依据。建议通过官方渠道核实最新判例。"
        )

        content = "\n\n---\n\n".join(output_parts)

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            content=content,
            metadata={"query": query, "result_count": len(results)},
        )

    def _search_cases(self, query: str, court_level: str | None = None, case_type: str | None = None) -> list[dict]:
        """
        检索案例（关键词 + 二元组混合匹配，分数归一化到 0~1）

        匹配权重说明：
        - keyword_score: 查询词在可搜索文本中的命中数（每词 2 分）
        - direct_match: 查询词在 case keywords 列表中的命中数（每词 3 分，精确匹配权重更高）
        - bigram_score: 字符二元组 Jaccard 相似度（0~1，×5 归一化到与其他分数可比的量级）
        - 归一化: match_score / max_possible_score → 0~1 范围
        """
        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) >= 2]

        results = []
        for case in self.cases:
            # 过滤条件
            if court_level and court_level not in case.get("court", ""):
                continue
            if case_type and case_type != case.get("case_type", ""):
                continue

            searchable = (
                f"{case.get('title', '')} {case.get('issue', '')} "
                f"{case.get('holding', '')} {' '.join(case.get('keywords', []))}"
            ).lower()

            # 关键词匹配（权重 2）
            keyword_score = sum(2 for w in query_words if w in searchable)

            # 关键词直接匹配 case keywords 列表（权重 3）
            case_keywords_text = " ".join(case.get("keywords", [])).lower()
            direct_match = sum(3 for w in query_words if w in case_keywords_text)

            # 字符二元组 Jaccard 相似度（0~1，×5 归一化）
            bigram_score = bigram_jaccard(query_lower, searchable) * 5

            raw_score = keyword_score + direct_match + bigram_score
            if raw_score <= 0:
                continue

            # 归一化到 0~1：最大可能分数 = 所有查询词都命中(2+3) + 完美二元组(5)
            max_possible = len(query_words) * 5 + 5 if query_words else 1
            normalized = min(1.0, raw_score / max_possible)

            results.append({**case, "match_score": round(normalized, 3)})

        results.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return results[:5]
