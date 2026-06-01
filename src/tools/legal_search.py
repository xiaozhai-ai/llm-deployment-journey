"""
法规检索工具
- 基于 ChromaDB 向量检索相关法律法规
- 支持关键词和语义混合搜索
"""

from typing import Any

from src.tools.base import BaseTool, ToolDefinition, ToolResult


class LegalSearchTool(BaseTool):
    """法规检索工具"""

    def __init__(self, vector_store=None):
        """
        初始化

        Args:
            vector_store: VectorStore 实例
        """
        self.vector_store = vector_store
        self._local_kb = []  # 本地知识库回退

    def set_vector_store(self, vector_store):
        """设置向量存储"""
        self.vector_store = vector_store

    def set_local_kb(self, provisions: list):
        """设置本地知识库回退"""
        self._local_kb = provisions

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_legal_provision",
            description=(
                "检索中国现行法律法规，获取相关法条内容。"
                "当你需要确认某条款的法律依据、不确定某法律规定的内容、"
                "或需要引用具体法条时，调用此工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "检索关键词或问题描述。例如：'违约金上限'、'格式条款无效情形'、'个人信息跨境传输条件'"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": "可选的分类过滤",
                        "enum": ["合同", "个人信息保护", "数据安全", "消费者保护", "基本原则", "其他"],
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, arguments: dict[str, Any], tool_call_id: str = "") -> ToolResult:
        query = arguments.get("query", "")
        category = arguments.get("category")

        if not query:
            return ToolResult(
                tool_call_id=tool_call_id, tool_name=self.name, success=False, content="错误：检索关键词不能为空"
            )

        results = []

        # 尝试向量检索
        if self.vector_store:
            try:
                vector_results = self.vector_store.hybrid_search(query=query, top_k=5, category_filter=category)
                for vr in vector_results:
                    meta = vr.metadata
                    results.append(
                        {
                            "law": meta.get("law", ""),
                            "article": meta.get("article", ""),
                            "title": meta.get("title", ""),
                            "content": meta.get("content", ""),
                            "score": round(vr.score, 3),
                        }
                    )
            except Exception as e:
                results.append({"error": f"向量检索失败: {str(e)}"})

        # 回退到本地关键词搜索
        if not results and self._local_kb:
            results = self._keyword_search(query, category)

        if not results:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                content=f"未找到与「{query}」直接相关的法条。建议：1. 调整检索关键词；2. 扩大分类范围；3. 此领域可能缺乏明确的成文法规定。",
            )

        # 格式化结果
        output_parts = [f"📋 法规检索结果（关键词：{query}）\n"]

        for i, r in enumerate(results, 1):
            if "error" in r:
                output_parts.append(f"⚠️ {r['error']}")
                continue

            output_parts.append(
                f"**{i}. 《{r['law']}》{r['article']}（{r['title']}）**\n{r['content']}\n> 相关度: {r['score']:.0%}"
            )

        content = "\n\n---\n\n".join(output_parts)

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            content=content,
            metadata={"query": query, "result_count": len(results)},
        )

    def _keyword_search(self, query: str, category: str | None) -> list:
        """关键词回退搜索（中文字符 n-gram 匹配）"""
        results = []
        query_lower = query.lower()
        query_ngrams = self._extract_ngrams(query_lower)

        for provision in self._local_kb:
            if category and provision.get("category") != category:
                continue

            text = f"{provision.get('law', '')} {provision.get('title', '')} {provision.get('content', '')}".lower()

            # 子串匹配（精确）
            exact_match = query_lower in text

            # n-gram 匹配（模糊）
            text_ngrams = self._extract_ngrams(text)
            if query_ngrams and text_ngrams:
                overlap = len(query_ngrams & text_ngrams)
                ngram_score = overlap / len(query_ngrams)
            else:
                ngram_score = 0

            # 计算综合分数
            if exact_match:
                score = 0.9
            elif ngram_score >= 0.5:
                score = 0.4 + ngram_score * 0.4
            elif ngram_score > 0:
                score = ngram_score * 0.5
            else:
                continue

            results.append(
                {
                    "law": provision.get("law", ""),
                    "article": provision.get("article", ""),
                    "title": provision.get("title", ""),
                    "content": provision.get("content", "")[:300],
                    "score": round(score, 3),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:5]

    @staticmethod
    def _extract_ngrams(text: str, n: int = 2) -> set:
        """提取字符 n-gram（用于中文模糊匹配）"""
        # 移除空格和标点
        cleaned = "".join(c for c in text if c.isalnum())
        if len(cleaned) < n:
            return {cleaned} if cleaned else set()
        return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}
