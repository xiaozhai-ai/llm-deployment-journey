"""
LegalSearchTool 单元测试

覆盖：
- 向量检索成功/失败
- 关键词回退搜索
- n-gram 模糊匹配
- 子串精确匹配
- 分类过滤
- 空查询处理
- 本地知识库为空
"""

from unittest.mock import MagicMock

import pytest

from src.llm.tools.legal_search import LegalSearchTool


@pytest.fixture
def local_provisions():
    return [
        {
            "law": "民法典",
            "article": "第五百七十七条",
            "title": "违约责任",
            "content": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
            "category": "合同",
            "keywords": ["违约责任", "继续履行", "赔偿损失"],
        },
        {
            "law": "民法典",
            "article": "第五百零六条",
            "title": "免责条款无效情形",
            "content": "合同中的下列免责条款无效：（一）造成对方人身损害的；（二）因故意或者重大过失造成对方财产损失的。",
            "category": "合同",
            "keywords": ["免责条款", "无效", "人身损害"],
        },
        {
            "law": "个人信息保护法",
            "article": "第十三条",
            "title": "个人信息处理条件",
            "content": "符合下列情形之一的，个人信息处理者方可处理个人信息：（一）取得个人的同意...",
            "category": "个人信息保护",
            "keywords": ["个人信息", "同意", "处理条件"],
        },
    ]


@pytest.fixture
def tool_with_local_kb(local_provisions):
    tool = LegalSearchTool()
    tool.set_local_kb(local_provisions)
    return tool


# ============================================
# 空查询/空知识库
# ============================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": ""})
        assert result.success is False
        assert "不能为空" in result.content

    @pytest.mark.asyncio
    async def test_no_vector_store_no_local_kb(self):
        tool = LegalSearchTool()
        result = await tool.execute({"query": "违约金"})
        assert result.success is True
        assert "未找到" in result.content


# ============================================
# 关键词回退搜索
# ============================================


class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_exact_match(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": "违约责任"})
        assert result.success is True
        assert "违约责任" in result.content
        assert "民法典" in result.content

    @pytest.mark.asyncio
    async def test_ngram_fuzzy_match(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": "违约赔偿"})
        assert result.success is True
        # 应该能匹配到违约责任条款（n-gram 重叠）
        assert "违约" in result.content

    @pytest.mark.asyncio
    async def test_no_match(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": "量子计算"})
        assert result.success is True
        assert "未找到" in result.content

    @pytest.mark.asyncio
    async def test_category_filter(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": "个人信息", "category": "个人信息保护"})
        assert result.success is True
        assert "个人信息" in result.content

    @pytest.mark.asyncio
    async def test_category_filter_excludes(self, tool_with_local_kb):
        result = await tool_with_local_kb.execute({"query": "个人信息", "category": "合同"})
        assert result.success is True
        # 个人信息相关条款不属于"合同"分类
        assert "未找到" in result.content


# ============================================
# 向量检索
# ============================================


class TestVectorSearch:
    @pytest.mark.asyncio
    async def test_vector_search_success(self):
        mock_vs = MagicMock()
        mock_result = MagicMock()
        mock_result.metadata = {
            "law": "民法典",
            "article": "第五百七十七条",
            "title": "违约责任",
            "content": "违约责任内容",
        }
        mock_result.score = 0.85
        mock_vs.hybrid_search.return_value = [mock_result]

        tool = LegalSearchTool(vector_store=mock_vs)
        result = await tool.execute({"query": "违约金"})
        assert result.success is True
        assert "民法典" in result.content
        assert "85%" in result.content

    @pytest.mark.asyncio
    async def test_vector_search_fallback_to_local(self, local_provisions):
        mock_vs = MagicMock()
        mock_vs.hybrid_search.side_effect = RuntimeError("ChromaDB 连接失败")

        tool = LegalSearchTool(vector_store=mock_vs)
        tool.set_local_kb(local_provisions)
        result = await tool.execute({"query": "违约责任"})
        assert result.success is True
        # 回退到本地搜索
        assert "违约" in result.content


# ============================================
# ToolDefinition
# ============================================


class TestDefinition:
    def test_name(self):
        tool = LegalSearchTool()
        assert tool.name == "search_legal_provision"

    def test_openai_schema(self):
        tool = LegalSearchTool()
        schema = tool.definition.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search_legal_provision"
        assert "query" in schema["function"]["parameters"]["properties"]
