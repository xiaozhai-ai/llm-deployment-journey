"""
法条匹配模块（重构版）
- 混合检索：向量语义 + 关键词
- 法条相关度排序优化
"""

from dataclasses import dataclass

import yaml

from src.core.config import get_paths_config
from src.llm.vector_store import VectorStore


@dataclass
class LegalProvision:
    """法条"""

    law: str
    article: str
    title: str
    content: str
    category: str
    keywords: list[str]


@dataclass
class LegalMatch:
    """法条匹配结果"""

    provision: LegalProvision
    match_reason: str
    relevance_score: float


class LegalMatcher:
    """法条匹配器（增强版）"""

    def __init__(self, kb_path: str | None = None, vector_store: VectorStore | None = None):
        self.provisions: list[LegalProvision] = []
        self.vector_store = vector_store or VectorStore()
        self._provisions_loaded = False

        if kb_path:
            self._load_knowledge_base(kb_path)
        else:
            # 从配置模块获取路径
            paths_config = get_paths_config()
            default_path = paths_config["kb_path"]
            if default_path.exists():
                self._load_knowledge_base(str(default_path))

    def _load_knowledge_base(self, path: str):
        """加载法律法规知识库"""
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.provisions = []
        batch_items = []
        for item in config.get("legal_provisions", []):
            provision = LegalProvision(
                law=item["law"],
                article=item["article"],
                title=item["title"],
                content=item["content"],
                category=item.get("category", "其他"),
                keywords=item.get("keywords", []),
            )
            self.provisions.append(provision)
            batch_items.append(item)

        # 批量同步到向量库（自动跳过已存在条目）
        if batch_items:
            self.vector_store.add_provisions_batch(batch_items)

        self._provisions_loaded = True

    def match_provisions(self, risk_description: str, risk_category: str = "") -> list[LegalMatch]:
        """
        混合检索匹配法条

        Args:
            risk_description: 风险描述
            risk_category: 风险类别

        Returns:
            法条匹配结果列表
        """
        # 1. 向量语义检索
        vector_results = self.vector_store.hybrid_search(
            query=risk_description, top_k=5, category_filter=risk_category if risk_category else None
        )

        matches = []
        for vr in vector_results:
            provision = self._metadata_to_provision(vr.metadata)
            if provision:
                matches.append(
                    LegalMatch(
                        provision=provision,
                        match_reason=self._get_match_reason(risk_description, provision),
                        relevance_score=vr.score,
                    )
                )

        # 2. 如果向量检索结果不足，补充关键词检索
        if len(matches) < 3:
            keyword_matches = self._keyword_fallback(
                risk_description, risk_category, exclude_ids={m.provision.article for m in matches}
            )
            matches.extend(keyword_matches)

        # 按相关度排序
        matches.sort(key=lambda m: m.relevance_score, reverse=True)
        return matches[:5]

    def _metadata_to_provision(self, metadata: dict) -> LegalProvision | None:
        """将向量库元数据转换为法条对象"""
        if not metadata or "law" not in metadata:
            return None

        return LegalProvision(
            law=metadata.get("law", ""),
            article=metadata.get("article", ""),
            title=metadata.get("title", ""),
            content=metadata.get("content", ""),
            category=metadata.get("category", "其他"),
            keywords=metadata.get("keywords", "").split(",") if metadata.get("keywords") else [],
        )

    def _keyword_fallback(self, text: str, category: str, exclude_ids: set) -> list[LegalMatch]:
        """关键词回退检索"""
        matches = []
        text_lower = text.lower()

        for provision in self.provisions:
            # 排除已匹配的
            if provision.article in exclude_ids:
                continue

            score = self._calculate_keyword_relevance(text_lower, provision, category)
            if score > 0.3:
                matches.append(
                    LegalMatch(
                        provision=provision, match_reason=self._get_match_reason(text, provision), relevance_score=score
                    )
                )

        return matches

    def _calculate_keyword_relevance(self, text: str, provision: LegalProvision, category: str) -> float:
        """计算关键词相关度"""
        score = 0.0

        # 关键词匹配（provision 的 keywords 是人工标注的中文短语）
        for keyword in provision.keywords:
            if keyword.lower() in text:
                score += 0.3

        # 内容匹配：从法条内容中提取 2-4 字短语做子串匹配
        # 提取法条标题/核心短语（中文标题通常 2-8 字）
        title = provision.title.lower()
        if title and title in text:
            score += 0.3

        # 分类匹配
        if category and category == provision.category:
            score += 0.2

        return min(score, 1.0)

    def _get_match_reason(self, text: str, provision: LegalProvision) -> str:
        """获取匹配原因"""
        text_lower = text.lower()
        matched = [kw for kw in provision.keywords if kw.lower() in text_lower]
        if matched:
            return f"匹配关键词：{', '.join(matched)}"
        return "与风险描述相关"

    def search_by_keyword(self, keyword: str) -> list[LegalProvision]:
        """按关键词搜索法条"""
        results = []
        keyword_lower = keyword.lower()

        for provision in self.provisions:
            if (
                keyword_lower in provision.content.lower()
                or keyword_lower in provision.title.lower()
                or any(keyword_lower in kw.lower() for kw in provision.keywords)
            ):
                results.append(provision)

        return results

    def get_provision_by_citation(self, law: str, article: str) -> LegalProvision | None:
        """按引用获取法条"""
        for provision in self.provisions:
            if law in provision.law and article in provision.article:
                return provision
        return None

    def format_citation(self, provision: LegalProvision) -> str:
        """格式化法条引用"""
        return f"《{provision.law}》{provision.article}（{provision.title}）"

    def get_all_laws(self) -> list[str]:
        """获取所有法律名称"""
        return list(set(p.law for p in self.provisions))

    def get_categories(self) -> list[str]:
        """获取所有分类"""
        return list(set(p.category for p in self.provisions))
