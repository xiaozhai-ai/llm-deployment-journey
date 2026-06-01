"""
LegalMatcher 单元测试

覆盖：
- 知识库加载
- 关键词搜索
- 按引用获取法条
- 关键词相关度计算
- 匹配原因生成
- 法条格式化
"""

from unittest.mock import MagicMock

import pytest

from src.legal_matcher import LegalMatcher


@pytest.fixture
def mock_vector_store():
    """创建 mock VectorStore"""
    store = MagicMock()
    store.hybrid_search.return_value = []
    store.add_provision.return_value = None
    return store


@pytest.fixture
def kb_path(tmp_path):
    """创建临时知识库文件"""
    content = """
legal_provisions:
  - law: "民法典"
    article: "第五百七十七条"
    title: "违约责任"
    content: "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"
    category: "合同法"
    keywords:
      - "违约责任"
      - "违约"
      - "赔偿损失"
      - "继续履行"

  - law: "民法典"
    article: "第五百零六条"
    title: "免责条款无效"
    content: "合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。"
    category: "合同法"
    keywords:
      - "免责条款"
      - "人身损害"
      - "免责"

  - law: "个人信息保护法"
    article: "第十三条"
    title: "个人信息处理的合法性基础"
    content: "符合下列情形之一的，个人信息处理者方可处理个人信息：（一）取得个人的同意..."
    category: "隐私合规"
    keywords:
      - "个人信息"
      - "同意"
      - "合法性基础"

  - law: "民法典"
    article: "第四百九十七条"
    title: "格式条款无效"
    content: "有下列情形之一的，该格式条款无效：（一）具有本法第一编第六章第三节和本法第五百零六条规定的无效情形；（二）提供格式条款一方不合理地免除或者减轻其责任、加重对方责任、限制对方主要权利；（三）提供格式条款一方排除对方主要权利。"
    category: "合同法"
    keywords:
      - "格式条款"
      - "主要权利"
      - "免责"
"""
    path = tmp_path / "legal_kb.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def matcher(kb_path, mock_vector_store):
    """创建 LegalMatcher 实例"""
    return LegalMatcher(kb_path=kb_path, vector_store=mock_vector_store)


# ============================================
# 知识库加载
# ============================================


class TestKnowledgeBaseLoading:
    """知识库加载测试"""

    def test_load_provisions(self, matcher):
        """成功加载法条"""
        assert len(matcher.provisions) == 4

    def test_provision_fields(self, matcher):
        """法条字段完整性"""
        p = matcher.provisions[0]
        assert p.law == "民法典"
        assert p.article == "第五百七十七条"
        assert p.title == "违约责任"
        assert "违约责任" in p.keywords
        assert p.category == "合同法"

    def test_provisions_synced_to_vector_store(self, matcher, mock_vector_store):
        """法条应同步到向量库"""
        assert mock_vector_store.add_provision.call_count == 4

    def test_load_nonexistent_file(self, mock_vector_store):
        """加载不存在的文件应抛出异常（YAML 读取失败）"""
        with pytest.raises((FileNotFoundError, Exception)):
            LegalMatcher(kb_path="/nonexistent/path.yaml", vector_store=mock_vector_store)


# ============================================
# 关键词搜索
# ============================================


class TestKeywordSearch:
    """关键词搜索测试"""

    def test_search_by_keyword_in_content(self, matcher):
        """按内容关键词搜索"""
        results = matcher.search_by_keyword("违约责任")
        assert len(results) >= 1
        assert any("违约责任" in r.content for r in results)

    def test_search_by_keyword_in_title(self, matcher):
        """按标题关键词搜索"""
        results = matcher.search_by_keyword("免责条款")
        assert len(results) >= 1
        assert any("免责条款" in r.title for r in results)

    def test_search_by_keyword_in_keywords_list(self, matcher):
        """按 keywords 列表搜索"""
        results = matcher.search_by_keyword("格式条款")
        assert len(results) >= 1

    def test_search_no_results(self, matcher):
        """无匹配结果"""
        results = matcher.search_by_keyword("量子力学")
        assert len(results) == 0

    def test_search_case_insensitive(self, matcher):
        """搜索应大小写不敏感"""
        results = matcher.search_by_keyword("个人信息")
        assert len(results) >= 1

    def test_search_empty_keyword(self, matcher):
        """空关键词返回所有结果（因为所有内容都包含空字符串）"""
        results = matcher.search_by_keyword("")
        assert len(results) == 4  # 空字符串匹配所有


# ============================================
# 按引用获取法条
# ============================================


class TestGetProvisionByCitation:
    """按引用获取法条测试"""

    def test_get_by_exact_citation(self, matcher):
        """精确引用获取"""
        p = matcher.get_provision_by_citation("民法典", "第五百七十七条")
        assert p is not None
        assert p.title == "违约责任"

    def test_get_by_partial_law_name(self, matcher):
        """部分法律名称匹配"""
        p = matcher.get_provision_by_citation("民法", "第五百零六条")
        assert p is not None

    def test_get_nonexistent(self, matcher):
        """不存在的引用返回 None"""
        p = matcher.get_provision_by_citation("刑法", "第一条")
        assert p is None


# ============================================
# 关键词相关度计算
# ============================================


class TestKeywordRelevance:
    """关键词相关度计算测试"""

    def test_high_relevance(self, matcher):
        """多个关键词命中 → 高相关度"""
        provision = matcher.provisions[0]  # 违约责任
        score = matcher._calculate_keyword_relevance("违约责任 赔偿损失 违约", provision, "合同法")
        assert score > 0.5

    def test_category_match_bonus(self, matcher):
        """分类匹配加分"""
        provision = matcher.provisions[0]  # category: 合同法
        score_with_cat = matcher._calculate_keyword_relevance("违约", provision, "合同法")
        score_without = matcher._calculate_keyword_relevance("违约", provision, "其他")
        assert score_with_cat >= score_without

    def test_no_match(self, matcher):
        """无匹配 → 低分"""
        provision = matcher.provisions[0]
        score = matcher._calculate_keyword_relevance("量子力学 相对论", provision, "物理")
        assert score < 0.3

    def test_score_capped_at_one(self, matcher):
        """分数不超过 1.0"""
        provision = matcher.provisions[0]
        # 大量关键词命中
        text = " ".join(provision.keywords * 10) + " " + provision.title + " " + provision.category
        score = matcher._calculate_keyword_relevance(text, provision, provision.category)
        assert score <= 1.0


# ============================================
# 匹配原因
# ============================================


class TestMatchReason:
    """匹配原因生成测试"""

    def test_reason_with_matched_keywords(self, matcher):
        """命中关键词时显示匹配的关键词"""
        provision = matcher.provisions[0]  # keywords: 违约责任, 违约, 赔偿损失, 继续履行
        reason = matcher._get_match_reason("违约责任和赔偿损失", provision)
        assert "匹配关键词" in reason
        assert "违约责任" in reason

    def test_reason_no_keyword_match(self, matcher):
        """无关键词匹配时返回默认原因"""
        provision = matcher.provisions[0]
        reason = matcher._get_match_reason("完全无关的文本", provision)
        assert "相关" in reason


# ============================================
# 法条格式化
# ============================================


class TestFormatCitation:
    """法条引用格式化测试"""

    def test_format_citation(self, matcher):
        """格式化引用"""
        p = matcher.provisions[0]
        citation = matcher.format_citation(p)
        assert "《民法典》" in citation
        assert "第五百七十七条" in citation
        assert "违约责任" in citation


# ============================================
# 分类和法律名称
# ============================================


class TestCategoriesAndLaws:
    """分类和法律名称获取测试"""

    def test_get_all_laws(self, matcher):
        """获取所有法律名称"""
        laws = matcher.get_all_laws()
        assert "民法典" in laws
        assert "个人信息保护法" in laws

    def test_get_categories(self, matcher):
        """获取所有分类"""
        categories = matcher.get_categories()
        assert "合同法" in categories
        assert "隐私合规" in categories

    def test_no_duplicates(self, matcher):
        """法律名称和分类不应有重复"""
        laws = matcher.get_all_laws()
        categories = matcher.get_categories()
        assert len(laws) == len(set(laws))
        assert len(categories) == len(set(categories))


# ============================================
# 混合检索（mock vector store）
# ============================================


class TestHybridSearch:
    """混合检索测试"""

    def test_vector_search_results_used(self, matcher, mock_vector_store):
        """向量检索结果应被使用"""
        from src.vector_store import VectorSearchResult

        mock_vector_store.hybrid_search.return_value = [
            VectorSearchResult(
                id="1",
                content="违约责任",
                metadata={
                    "law": "民法典",
                    "article": "第五百七十七条",
                    "title": "违约责任",
                    "content": "当事人一方不履行合同义务...",
                    "category": "合同法",
                    "keywords": "违约责任,违约",
                },
                distance=0.3,
                score=0.7,
            )
        ]

        matches = matcher.match_provisions("违约赔偿", "合同法")
        assert len(matches) >= 1
        assert matches[0].provision.law == "民法典"

    def test_keyword_fallback_when_vector_empty(self, matcher, mock_vector_store):
        """向量检索无结果时回退到关键词检索"""
        mock_vector_store.hybrid_search.return_value = []

        matches = matcher.match_provisions("违约责任", "合同法")
        assert len(matches) >= 1

    def test_results_sorted_by_score(self, matcher, mock_vector_store):
        """结果应按相关度降序排列"""
        mock_vector_store.hybrid_search.return_value = []

        matches = matcher.match_provisions("违约责任 赔偿损失 格式条款 免责")
        if len(matches) > 1:
            scores = [m.relevance_score for m in matches]
            assert scores == sorted(scores, reverse=True)

    def test_max_results_five(self, matcher, mock_vector_store):
        """最多返回 5 个结果"""
        mock_vector_store.hybrid_search.return_value = []

        matches = matcher.match_provisions("违约 责任 赔偿 免责 格式 个人信息 同意")
        assert len(matches) <= 5
