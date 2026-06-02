"""
向量数据库模块 (ChromaDB)
- 法律法规知识库向量化存储与检索
- 多路召回：向量语义 + 关键词精确匹配 + 法律术语强制召回
- RRF 融合排序（Reciprocal Rank Fusion）
- 支持增量更新法规
- 增强版：统一异常处理 + 降级策略
"""

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from src.exceptions import VectorSearchError, VectorStoreInitError
from src.legal_terms import FORCE_RECALL_TERMS, expand_query, get_legal_terms
from src.logger import logger_manager

try:
    import chromadb

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logger_manager.warning("ChromaDB 未安装，向量检索功能将不可用")

ONNX_MODEL_FILE = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx" / "model.onnx"


@dataclass
class VectorSearchResult:
    """向量检索结果"""

    id: str
    content: str
    metadata: dict
    distance: float
    score: float


class VectorStore:
    """
    向量存储管理器

    使用 ChromaDB 作为嵌入式向量数据库，无需外部服务。
    支持法规条文的多路召回和精准匹配。
    """

    COLLECTION_NAME = "legal_provisions"

    def __init__(self, persist_dir: str | None = None, embedding_model: str | None = None):
        self.persist_dir = persist_dir or os.path.join(os.path.dirname(__file__), "..", "chroma_db")
        self.embedding_model = embedding_model
        self.client = None
        self.collection = None
        self._initialized = False
        self._model_ready = False

        # 关键词索引（用于精确匹配和强制召回）
        self._keyword_index: dict[str, dict] = {}
        # 关键词→法条ID 反向索引
        self._term_to_ids: dict[str, set[str]] = {}
        self._index_lock = threading.Lock()

    def initialize(self):
        """初始化向量库（失败时允许重试）"""
        if self._initialized:
            return

        if not CHROMA_AVAILABLE:
            logger_manager.warning("ChromaDB 不可用，将仅使用关键词匹配模式")
            self._initialized = True
            return

        try:
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            self._init_collection()
            logger_manager.info(f"ChromaDB 初始化成功，持久化目录: {self.persist_dir}")
            self._initialized = True
            self._model_ready = ONNX_MODEL_FILE.exists()
            if not self._model_ready:
                logger_manager.info("嵌入模型未就绪，降级到关键词匹配模式（后台下载中）")
        except Exception as e:
            logger_manager.warning(f"ChromaDB 初始化失败: {e}")
            self.client = None
            self.collection = None
            self._initialized = True
            self._model_ready = False

    def _init_collection(self):
        """初始化或创建集合"""
        try:
            self.collection = self.client.get_collection(self.COLLECTION_NAME)
            logger_manager.debug(f"成功加载集合: {self.COLLECTION_NAME}")
        except Exception as e:
            logger_manager.debug(f"集合 {self.COLLECTION_NAME} 不存在，将创建新集合: {e}")
            try:
                self.collection = self.client.create_collection(
                    name=self.COLLECTION_NAME, metadata={"description": "中国法律法规知识库"}
                )
                logger_manager.info(f"创建新集合: {self.COLLECTION_NAME}")
            except Exception as e:
                logger_manager.error(f"创建 ChromaDB 集合失败: {e}")
                raise VectorStoreInitError(f"创建向量集合失败: {e}") from e

    def add_provision(
        self, law: str, article: str, title: str, content: str, category: str = "", keywords: list[str] = None
    ) -> str:
        """添加法条到向量库"""
        self.initialize()

        entry_id = self._generate_id(law, article)

        # 构建文档文本
        document = f"{law} {article} {title} {content}"

        # 元数据
        metadata = {
            "law": law,
            "article": article,
            "title": title,
            "category": category,
            "keywords": ",".join(keywords) if keywords else "",
            "content": content,
        }

        # 删除旧条目
        try:
            if self.collection:
                self.collection.delete(ids=[entry_id])
        except Exception as e:
            logger_manager.debug(f"删除旧条目失败（忽略）: {e}")

        # 添加到向量库
        if CHROMA_AVAILABLE and self.collection:
            try:
                self.collection.add(documents=[document], metadatas=[metadata], ids=[entry_id])
            except RuntimeError as e:
                if "downloading" in str(e).lower() or "not found" in str(e).lower():
                    if not hasattr(self, "_model_warned"):
                        logger_manager.info("嵌入模型下载中，法条暂存关键词索引，模型就绪后自动补入向量库")
                        self._model_warned = True
                else:
                    logger_manager.warning(f"向量库添加失败: {e}")

        # 更新关键词索引（线程安全）
        with self._index_lock:
            self._keyword_index[entry_id] = {
                "law": law,
                "article": article,
                "title": title,
                "content": content,
                "category": category,
                "keywords": keywords or [],
                "search_text": f"{law} {article} {title} {content} {' '.join(keywords or [])}".lower(),
            }

            # 更新反向索引
            all_terms = set(keywords or [])
            # 从内容中提取法律术语
            for term in FORCE_RECALL_TERMS:
                for variant in FORCE_RECALL_TERMS[term]:
                    if variant in content.lower() or variant in title.lower():
                        all_terms.add(term)

            for term in all_terms:
                if term not in self._term_to_ids:
                    self._term_to_ids[term] = set()
                self._term_to_ids[term].add(entry_id)

        return entry_id

    def add_provisions_batch(self, provisions: list[dict]):
        """批量添加法条（自动跳过已存在的条目）"""
        self.initialize()

        # 查询已存在的 ID，避免重复 delete+add
        existing_ids: set[str] = set()
        if CHROMA_AVAILABLE and self.collection:
            try:
                all_ids = self.collection.get()["ids"]
                existing_ids = set(all_ids)
            except Exception:
                pass

        for p in provisions:
            entry_id = self._generate_id(p.get("law", ""), p.get("article", ""))
            if entry_id in existing_ids:
                # 已存在，仅更新关键词索引
                with self._index_lock:
                    self._keyword_index[entry_id] = {
                        "law": p.get("law", ""),
                        "article": p.get("article", ""),
                        "title": p.get("title", ""),
                        "content": p.get("content", ""),
                        "category": p.get("category", ""),
                        "keywords": p.get("keywords", []),
                    }
                continue

            self.add_provision(
                law=p.get("law", ""),
                article=p.get("article", ""),
                title=p.get("title", ""),
                content=p.get("content", ""),
                category=p.get("category", ""),
                keywords=p.get("keywords", []),
            )

    def search(self, query: str, top_k: int = 5, category_filter: str | None = None) -> list[VectorSearchResult]:
        """检索相关法条"""
        return self.hybrid_search(query, top_k, category_filter)

    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        category_filter: str | None = None,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[VectorSearchResult]:
        """
        多路召回 + RRF 融合排序

        召回路数：
        1. 向量语义检索（ChromaDB）
        2. 关键词精确检索
        3. 法律术语强制召回

        降级策略：如果向量检索失败，自动回退到关键词匹配
        """
        self.initialize()

        all_results: dict[str, tuple[VectorSearchResult, float, float]] = {}

        # 路1: 向量语义检索（可能失败，自动降级）
        if CHROMA_AVAILABLE and self.collection:
            try:
                vector_results = self._vector_search(query, top_k * 2, category_filter)
                for r in vector_results:
                    all_results[r.id] = (r, r.score, 0.0)
            except Exception as e:
                logger_manager.warning(f"向量检索失败，将仅使用关键词匹配: {e}")
                # 继续执行关键词检索

        # 路2: 关键词检索（含查询扩展）
        try:
            keyword_results = self._keyword_search_expanded(query, top_k * 2, category_filter)
            for r in keyword_results:
                if r.id in all_results:
                    existing = all_results[r.id]
                    all_results[r.id] = (existing[0], existing[1], r.score)
                else:
                    all_results[r.id] = (r, 0.0, r.score)
        except Exception as e:
            logger_manager.error(f"关键词检索失败: {e}")
            raise VectorSearchError(f"关键词检索失败: {e}") from e

        # 路3: 法律术语强制召回
        try:
            force_recall_results = self._force_recall(query, category_filter)
            for r in force_recall_results:
                if r.id in all_results:
                    existing = all_results[r.id]
                    # 强制召回结果给关键词高分
                    new_kw_score = max(existing[2], r.score)
                    all_results[r.id] = (existing[0], existing[1], new_kw_score)
                else:
                    all_results[r.id] = (r, 0.0, r.score)
        except Exception as e:
            logger_manager.warning(f"强制召回失败: {e}，将跳过此步骤")
            # 不阻断流程

        # RRF 融合排序
        final_results = self._rrf_merge(all_results, top_k)

        return final_results

    def _vector_search(
        self, query: str, top_k: int, category_filter: str | None = None, min_score: float = 0.3
    ) -> list[VectorSearchResult]:
        """向量语义检索"""
        try:
            where = None
            if category_filter:
                where = {"category": category_filter}

            results = self.collection.query(
                query_texts=[query], n_results=top_k, where=where, include=["documents", "metadatas", "distances"]
            )

            search_results = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                metadata = results["metadatas"][0][i]
                score = max(0, 1 - distance)

                if score >= min_score:
                    search_results.append(
                        VectorSearchResult(
                            id=doc_id,
                            content=metadata.get("content", ""),
                            metadata=metadata,
                            distance=distance,
                            score=score,
                        )
                    )

            return search_results

        except Exception as e:
            logger_manager.warning(f"向量检索失败: {e}，将返回空结果")
            return []

    def _keyword_search_expanded(
        self, query: str, top_k: int, category_filter: str | None = None
    ) -> list[VectorSearchResult]:
        """
        关键词检索（含法律术语查询扩展）

        例如查询"定金"→扩展为["定金", "定金罚则", "定金合同"]
        """
        # 扩展查询
        expanded_terms = expand_query(query)

        results = []
        for entry_id, entry in self._keyword_index.items():
            if category_filter and entry.get("category") != category_filter:
                continue

            score = self._keyword_relevance_expanded(query, expanded_terms, entry)

            if score > 0.1:
                results.append(
                    VectorSearchResult(
                        id=entry_id, content=entry["content"], metadata=entry, distance=1 - score, score=score
                    )
                )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _keyword_relevance_expanded(self, query: str, expanded_terms: list[str], entry: dict) -> float:
        """
        计算关键词相关度（支持法律术语精确匹配）

        精确匹配法律术语给更高权重
        """
        search_text = entry.get("search_text", "")
        if not search_text:
            return 0.0

        score = 0.0
        query_lower = query.lower()

        # 1. 原始查询词匹配（权重最高）
        if query_lower in search_text:
            score += 0.5

        # 2. 扩展词匹配
        for term in expanded_terms:
            if term.lower() in search_text:
                score += 0.2

        # 3. 法条关键词精确匹配
        entry_keywords = entry.get("keywords", [])
        for kw in entry_keywords:
            if kw.lower() in search_text:
                # 检查是否是法律术语精确匹配
                is_legal_term = any(kw in FORCE_RECALL_TERMS.get(t, []) for t in FORCE_RECALL_TERMS)
                if is_legal_term:
                    score += 0.4  # 法律术语精确匹配高权重
                else:
                    score += 0.15

        # 4. 标题匹配加权
        title = entry.get("title", "").lower()
        if query_lower in title:
            score += 0.3
        for term in expanded_terms:
            if term.lower() in title:
                score += 0.15

        return min(score, 2.0)  # 可以超过1，后续归一化

    def _force_recall(self, query: str, category_filter: str | None = None) -> list[VectorSearchResult]:
        """
        法律术语强制召回

        当查询中包含预定义的法律关键术语时，
        强制召回包含该术语的所有法条。
        """
        # 提取查询中的法律术语
        detected_terms = get_legal_terms(query)

        # 也从原始查询中提取（因为 get_legal_terms 是针对长文本的）
        query_lower = query.lower()
        for term, variants in FORCE_RECALL_TERMS.items():
            for variant in variants:
                if variant.lower() in query_lower:
                    if term not in detected_terms:
                        detected_terms.append(term)

        if not detected_terms:
            return []

        recalled_ids = set()
        for term in detected_terms:
            if term in self._term_to_ids:
                recalled_ids.update(self._term_to_ids[term])

        results = []
        for entry_id in recalled_ids:
            if entry_id not in self._keyword_index:
                continue

            entry = self._keyword_index[entry_id]
            if category_filter and entry.get("category") != category_filter:
                continue

            # 强制召回给基础分
            results.append(
                VectorSearchResult(
                    id=entry_id,
                    content=entry["content"],
                    metadata=entry,
                    distance=0.3,  # 默认距离
                    score=0.7,  # 基础分（不挤占精确匹配结果）
                )
            )

        return results

    def _rrf_merge(
        self, all_results: dict[str, tuple[VectorSearchResult, float, float]], top_k: int, k: int = 60
    ) -> list[VectorSearchResult]:
        """
        RRF (Reciprocal Rank Fusion) 融合排序

        公式: score = Σ 1 / (rank_i + k)

        k=60 是经验值，确保单路排名第一不会被多路排名靠后的结果稀释
        """
        if not all_results:
            return []

        # 按向量得分排序
        vector_ranked = sorted(all_results.items(), key=lambda x: x[1][1], reverse=True)
        vector_ranks = {id_: i + 1 for i, (id_, _) in enumerate(vector_ranked)}

        # 按关键词得分排序
        keyword_ranked = sorted(all_results.items(), key=lambda x: x[1][2], reverse=True)
        keyword_ranks = {id_: i + 1 for i, (id_, _) in enumerate(keyword_ranked)}

        # 计算 RRF 得分
        rrf_scores = {}
        for entry_id, (_result, _v_score, _k_score) in all_results.items():
            v_rank = vector_ranks.get(entry_id, len(all_results) + 1)
            k_rank = keyword_ranks.get(entry_id, len(all_results) + 1)

            rrf_score = 1.0 / (v_rank + k) + 1.0 / (k_rank + k)
            rrf_scores[entry_id] = rrf_score

        # 按 RRF 得分排序
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        final_results = []
        for entry_id in sorted_ids[:top_k]:
            result = all_results[entry_id][0]
            # 更新最终得分为 RRF 得分
            result.score = rrf_scores[entry_id]
            final_results.append(result)

        return final_results

    def _keyword_search(
        self, query: str, top_k: int, category_filter: str | None = None, min_score: float = 0.3
    ) -> list[VectorSearchResult]:
        """简单关键词检索（向后兼容）"""
        return self._keyword_search_expanded(query, top_k, category_filter)

    def delete_provision(self, law: str, article: str) -> bool:
        """删除法条"""
        self.initialize()
        entry_id = self._generate_id(law, article)

        try:
            if CHROMA_AVAILABLE and self.collection:
                self.collection.delete(ids=[entry_id])
            if entry_id in self._keyword_index:
                del self._keyword_index[entry_id]
            # 清理反向索引
            for term in list(self._term_to_ids.keys()):
                self._term_to_ids[term].discard(entry_id)
                if not self._term_to_ids[term]:
                    del self._term_to_ids[term]
            return True
        except Exception as e:
            logger_manager.debug(f"删除法条失败: {law} {article}: {e}")
            return False

    def get_entry_count(self) -> int:
        """获取条目总数"""
        self.initialize()
        if CHROMA_AVAILABLE and self.collection:
            return self.collection.count()
        return len(self._keyword_index)

    def clear(self):
        """清空向量库"""
        self.initialize()
        if CHROMA_AVAILABLE and self.collection:
            self.client.delete_collection(self.COLLECTION_NAME)
            self._init_collection()
        self._keyword_index.clear()
        self._term_to_ids.clear()

    @staticmethod
    def _generate_id(law: str, article: str) -> str:
        """生成法条唯一 ID"""
        raw = f"{law}_{article}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
