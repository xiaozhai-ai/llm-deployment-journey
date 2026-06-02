"""
ReportGenerator 单元测试

覆盖：
- Markdown 报告生成
- 结构化字典生成
- 风险等级排序（含 critical）
- 建议列表换行
- 条款预览省略号
- 免责声明
- 新鲜度段落异常隔离
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from src.output.report import ReportGenerator

# ============================================
# 测试用数据结构
# ============================================


@dataclass
class MockRiskItem:
    id: str = "RISK_001"
    rule_id: str = "RULE_001"
    name: str = "测试风险"
    category: str = "条款缺失"
    risk_level: str = "high"
    description: str = "测试描述"
    clause_position: str | None = None
    clause_content_preview: str | None = None
    legal_basis: str | None = None
    suggestion: str | None = None
    confidence: float = 0.8
    clause_id: int = 0
    clause_title: str = ""
    clause_line_range: str = ""
    cited_provisions: list[str] = field(default_factory=list)


@dataclass
class MockRiskResult:
    risks: list = field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0


@pytest.fixture
def generator():
    return ReportGenerator()


@pytest.fixture
def single_risk_result():
    risk = MockRiskItem(
        id="R1",
        name="违约责任缺失",
        category="条款缺失",
        risk_level="high",
        description="未约定违约责任",
        clause_position="第五条",
        clause_content_preview="甲方应按时付款" * 5,
        legal_basis="民法典第五百七十七条",
        suggestion="补充违约责任条款",
        confidence=0.85,
        clause_title="第五条 付款方式",
        clause_line_range="第10-15行",
        cited_provisions=["民法典第五百七十七条"],
    )
    return MockRiskResult(risks=[risk], high_count=1)


@pytest.fixture
def multi_level_risk_result():
    risks = [
        MockRiskItem(id="R1", name="低风险", risk_level="low", confidence=0.5),
        MockRiskItem(id="R2", name="严重风险", risk_level="critical", confidence=0.95),
        MockRiskItem(id="R3", name="中风险", risk_level="medium", confidence=0.6),
        MockRiskItem(id="R4", name="高风险", risk_level="high", confidence=0.8),
    ]
    return MockRiskResult(risks=risks, critical_count=1, high_count=1, medium_count=1, low_count=1)


# ============================================
# Markdown 报告生成
# ============================================


class TestGenerateReport:
    @patch("src.output.report.get_freshness_checker")
    def test_report_contains_header(self, mock_freshness, generator, single_risk_result):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = "时效性声明"
        mock_freshness.return_value = mock_checker

        report = generator.generate_report("测试合同.docx", "contract", single_risk_result, [])
        assert "📋 法务审查报告" in report
        assert "测试合同.docx" in report
        assert "合同" in report

    @patch("src.output.report.get_freshness_checker")
    def test_report_contains_risk_summary(self, mock_freshness, generator, single_risk_result):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        report = generator.generate_report("test.docx", "contract", single_risk_result, [])
        assert "📊 风险概览" in report
        assert "🔴 高风险" in report

    @patch("src.output.report.get_freshness_checker")
    def test_report_contains_disclaimer(self, mock_freshness, generator, single_risk_result):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = "时效性声明"
        mock_freshness.return_value = mock_checker

        report = generator.generate_report("test.docx", "contract", single_risk_result, [])
        assert "免责声明" in report
        assert "不构成正式法律意见" in report

    @patch("src.output.report.get_freshness_checker")
    def test_report_no_risks(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        empty_result = MockRiskResult()
        report = generator.generate_report("test.docx", "contract", empty_result, [])
        assert "未检测到明显风险" in report

    @patch("src.output.report.get_freshness_checker")
    def test_report_with_security_warning(self, mock_freshness, generator, single_risk_result):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        report = generator.generate_report(
            "test.docx", "contract", single_risk_result, [], security_warning="检测到敏感信息"
        )
        assert "🔒 安全提示" in report
        assert "检测到敏感信息" in report


# ============================================
# 风险等级排序
# ============================================


class TestRiskLevelSorting:
    @patch("src.output.report.get_freshness_checker")
    def test_critical_risks_first(self, mock_freshness, generator, multi_level_risk_result):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        report = generator.generate_report("test.docx", "contract", multi_level_risk_result, [])
        # critical 应排在最前
        critical_pos = report.index("严重风险")
        high_pos = report.index("高风险")
        medium_pos = report.index("中风险")
        low_pos = report.index("低风险")
        assert critical_pos < high_pos < medium_pos < low_pos

    @patch("src.output.report.get_freshness_checker")
    def test_critical_icon_in_report(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        risk = MockRiskItem(id="R1", name="严重问题", risk_level="critical", description="严重")
        result = MockRiskResult(risks=[risk], critical_count=1)
        report = generator.generate_report("test.docx", "contract", result, [])
        assert "🟣 严重风险" in report
        assert "🟣 严重风险 | 1" in report or "🟣 严重风险" in report


# ============================================
# 建议列表格式
# ============================================


class TestSuggestions:
    @patch("src.output.report.get_freshness_checker")
    def test_suggestions_on_separate_lines(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        risks = [
            MockRiskItem(id="R1", name="风险A", risk_level="high", suggestion="建议A"),
            MockRiskItem(id="R2", name="风险B", risk_level="medium", suggestion="建议B"),
        ]
        result = MockRiskResult(risks=risks, high_count=1, medium_count=1)
        report = generator.generate_report("test.docx", "contract", result, [])

        # 每条建议应独占一行
        assert "- [HIGH] 风险A: 建议A\n" in report
        assert "- [MEDIUM] 风险B: 建议B" in report

    @patch("src.output.report.get_freshness_checker")
    def test_no_suggestions(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        risk = MockRiskItem(id="R1", name="风险A", risk_level="high", suggestion=None)
        result = MockRiskResult(risks=[risk], high_count=1)
        report = generator.generate_report("test.docx", "contract", result, [])
        assert "暂无额外建议" in report


# ============================================
# 条款预览省略号
# ============================================


class TestClausePreview:
    @patch("src.output.report.get_freshness_checker")
    def test_short_preview_no_ellipsis(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        risk = MockRiskItem(id="R1", name="风险A", risk_level="high", clause_content_preview="短文本")
        result = MockRiskResult(risks=[risk], high_count=1)
        report = generator.generate_report("test.docx", "contract", result, [])
        assert "「短文本」" in report
        assert "短文本…" not in report

    @patch("src.output.report.get_freshness_checker")
    def test_long_preview_has_ellipsis(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        long_text = "甲" * 150
        risk = MockRiskItem(id="R1", name="风险A", risk_level="high", clause_content_preview=long_text)
        result = MockRiskResult(risks=[risk], high_count=1)
        report = generator.generate_report("test.docx", "contract", result, [])
        assert "…" in report


# ============================================
# 结构化字典生成
# ============================================


class TestGenerateReportDict:
    @patch("src.output.report.get_freshness_checker")
    def test_dict_contains_critical_level(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.get_freshness_disclaimer.return_value = "时效性声明"
        mock_freshness.return_value = mock_checker

        risk = MockRiskItem(id="R1", name="严重问题", risk_level="critical")
        result = MockRiskResult(risks=[risk], critical_count=1)
        d = generator.generate_report_dict("test.docx", "contract", result, [])

        assert d["risks"][0]["risk_level"] == "critical"
        assert d["risks"][0]["risk_level_cn"] == "严重"

    @patch("src.output.report.get_freshness_checker")
    def test_dict_risk_summary(self, mock_freshness, generator):
        mock_checker = MagicMock()
        mock_checker.get_freshness_disclaimer.return_value = ""
        mock_freshness.return_value = mock_checker

        risks = [
            MockRiskItem(id="R1", name="A", risk_level="high"),
            MockRiskItem(id="R2", name="B", risk_level="medium"),
        ]
        result = MockRiskResult(risks=risks, high_count=1, medium_count=1)
        d = generator.generate_report_dict("test.docx", "contract", result, [])

        assert d["risk_summary"]["total"] == 2
        assert d["risk_summary"]["high"] == 1
        assert d["risk_summary"]["medium"] == 1


# ============================================
# 新鲜度异常隔离
# ============================================


class TestFreshnessExceptionIsolation:
    @patch("src.output.report.get_freshness_checker")
    def test_freshness_section_exception_returns_empty(self, mock_freshness, generator):
        mock_freshness.side_effect = Exception("YAML 解析失败")
        section = generator.generate_freshness_section()
        assert section == ""

    @patch("src.output.report.get_freshness_checker")
    def test_report_generation_survives_freshness_failure(self, mock_freshness, generator, single_risk_result):
        # 第一次调用（generate_freshness_section）抛异常，第二次（_generate_disclaimer）正常
        mock_checker = MagicMock()
        mock_checker.check_all.side_effect = Exception("加载失败")
        mock_checker.get_freshness_disclaimer.return_value = "时效性声明"
        mock_freshness.return_value = mock_checker

        report = generator.generate_report("test.docx", "contract", single_risk_result, [])
        # 报告应正常生成，只是缺少新鲜度段落
        assert "📋 法务审查报告" in report
        assert "免责声明" in report
