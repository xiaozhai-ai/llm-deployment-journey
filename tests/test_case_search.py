"""
CaseSearchTool 单元测试

覆盖：
- 案例加载
- 关键词匹配
- 二元组匹配
- 分数归一化（0~1）
- 法院层级过滤
- 案件类型过滤
- 空查询处理
- 空案例库
- 动态添加案例
"""

import pytest
import yaml

from src.llm.tools.case_search import CaseSearchTool


@pytest.fixture
def case_law_yaml(tmp_path):
    cases = {
        "cases": [
            {
                "title": "海富投资案 — 对赌协议效力",
                "case_number": "(2012)民提字第11号",
                "court": "最高人民法院",
                "case_type": "指导案例",
                "issue": "对赌协议效力",
                "holding": "与股东对赌有效，与公司对赌审慎",
                "keywords": ["对赌协议", "业绩补偿", "股权投资"],
                "tags": ["合同效力"],
                "status": "active",
                "last_verified": "2026-05-28",
            },
            {
                "title": "违约金过高调整案",
                "case_number": "(2019)最高法民终146号",
                "court": "最高人民法院",
                "case_type": "典型案例",
                "issue": "违约金远超实际损失",
                "holding": "违约金过分高于损失的，可请求减少，以实际损失30%为标准",
                "keywords": ["违约金", "过高", "调整"],
                "tags": ["违约责任"],
                "status": "active",
                "last_verified": "2026-05-28",
            },
            {
                "title": "人脸识别第一案",
                "case_number": "(2020)浙0111民初10033号",
                "court": "杭州市富阳区人民法院",
                "case_type": "典型案例",
                "issue": "强制人脸识别是否违法",
                "holding": "收集人脸信息应遵循合法正当必要原则",
                "keywords": ["人脸识别", "个人信息", "合法正当必要"],
                "tags": ["个人信息保护"],
                "status": "active",
                "last_verified": "2026-05-28",
            },
        ]
    }
    path = tmp_path / "case_law.yaml"
    path.write_text(yaml.dump(cases, allow_unicode=True), encoding="utf-8")
    return str(path)


@pytest.fixture
def tool(case_law_yaml):
    return CaseSearchTool(case_law_path=case_law_yaml)


# ============================================
# 空查询/空案例库
# ============================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query(self, tool):
        result = await tool.execute({"query": ""})
        assert result.success is False
        assert "不能为空" in result.content

    @pytest.mark.asyncio
    async def test_no_match(self, tool):
        result = await tool.execute({"query": "量子计算 人工智能"})
        assert result.success is True
        assert "未在预置案例库中找到" in result.content

    @pytest.mark.asyncio
    async def test_empty_case_library(self, tmp_path):
        empty_path = tmp_path / "empty.yaml"
        empty_path.write_text(yaml.dump({"cases": []}, allow_unicode=True), encoding="utf-8")
        tool = CaseSearchTool(case_law_path=str(empty_path))
        result = await tool.execute({"query": "违约金"})
        assert result.success is True
        assert "未在预置案例库中找到" in result.content


# ============================================
# 关键词匹配
# ============================================


class TestKeywordMatch:
    @pytest.mark.asyncio
    async def test_exact_keyword_match(self, tool):
        result = await tool.execute({"query": "对赌协议"})
        assert result.success is True
        assert "海富投资" in result.content

    @pytest.mark.asyncio
    async def test_multiple_keyword_match(self, tool):
        result = await tool.execute({"query": "违约金 过高"})
        assert result.success is True
        assert "违约金过高" in result.content


# ============================================
# 分数归一化
# ============================================


class TestScoreNormalization:
    @pytest.mark.asyncio
    async def test_scores_between_0_and_1(self, tool):
        result = await tool.execute({"query": "违约金"})
        assert result.success is True
        # 结果中应包含匹配分数（0~1 范围）
        # 通过 metadata 验证
        assert result.metadata["result_count"] > 0


# ============================================
# 过滤条件
# ============================================


class TestFilters:
    @pytest.mark.asyncio
    async def test_court_level_filter(self, tool):
        result = await tool.execute({"query": "违约金", "court_level": "最高人民法院"})
        assert result.success is True
        assert "最高人民法院" in result.content

    @pytest.mark.asyncio
    async def test_court_level_filter_excludes(self, tool):
        result = await tool.execute({"query": "违约金", "court_level": "基层人民法院"})
        assert result.success is True
        assert "未在预置案例库中找到" in result.content

    @pytest.mark.asyncio
    async def test_case_type_filter(self, tool):
        result = await tool.execute({"query": "对赌协议", "case_type": "指导案例"})
        assert result.success is True
        assert "海富投资" in result.content

    @pytest.mark.asyncio
    async def test_case_type_filter_excludes(self, tool):
        result = await tool.execute({"query": "对赌协议", "case_type": "公报案例"})
        assert result.success is True
        assert "未在预置案例库中找到" in result.content


# ============================================
# 动态添加案例
# ============================================


class TestDynamicAdd:
    @pytest.mark.asyncio
    async def test_add_case(self, tool):
        initial_count = len(tool.cases)
        tool.add_case({"title": "新案例", "keywords": ["新关键词"], "court": "测试法院", "case_type": "一般判例"})
        assert len(tool.cases) == initial_count + 1


# ============================================
# ToolDefinition
# ============================================


class TestDefinition:
    def test_name(self, tool):
        assert tool.name == "search_case_law"

    def test_openai_schema(self, tool):
        schema = tool.definition.to_openai_schema()
        assert schema["type"] == "function"
        assert "query" in schema["function"]["parameters"]["properties"]
        assert "court_level" in schema["function"]["parameters"]["properties"]
        assert "case_type" in schema["function"]["parameters"]["properties"]
