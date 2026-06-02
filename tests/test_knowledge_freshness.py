"""
KnowledgeFreshnessChecker 单元测试

覆盖：
- 单例缓存（同参数不重复加载）
- 日期解析容错
- 新鲜度检查（warning / critical 阈值）
- 废止/修订法条警告
- overall_status 评估逻辑
- YAML 加载异常处理
- 格式化输出
- 免责声明
"""

from datetime import date

import pytest

from src.analysis.knowledge_freshness import (
    KnowledgeFreshnessChecker,
    LegalStatus,
)


@pytest.fixture
def checker(tmp_path):
    kb = tmp_path / "legal_kb.yaml"
    kb.write_text(
        "legal_provisions:\n"
        "- law: 民法典\n  article: 第577条\n  title: 违约责任\n"
        "  content: 当事人一方不履行合同义务\n  category: 合同\n"
        "  keywords: [违约]\n  status: active\n"
        "  effective_date: '2021-01-01'\n  last_verified: '2026-05-01'\n"
        "- law: 担保法\n  article: 第8条\n  title: 无效\n"
        "  content: 已废止\n  category: 担保\n  keywords: [担保]\n"
        "  status: repealed\n  repealed_by: 民法典\n"
        "  last_verified: '2020-01-01'\n"
        "- law: 民法典\n  article: 第496条\n  title: 格式条款\n"
        "  content: 格式条款\n  category: 合同\n  keywords: [格式]\n"
        "  status: active\n  last_verified: '2024-01-01'\n",
        encoding="utf-8",
    )
    case = tmp_path / "case_law.yaml"
    case.write_text(
        "cases:\n"
        "- title: 测试案例\n  case_number: (2025)民终1号\n"
        "  court: 最高法\n  issue: 测试\n  holding: 测试\n"
        "  keywords: [测试]\n  status: active\n  last_verified: '2025-06-01'\n",
        encoding="utf-8",
    )
    # 清除类缓存
    for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
        if hasattr(KnowledgeFreshnessChecker, attr):
            delattr(KnowledgeFreshnessChecker, attr)
    return KnowledgeFreshnessChecker(kb_path=str(kb), case_path=str(case))


class TestSingletonCache:
    def test_same_params_returns_cached(self, tmp_path):
        kb = tmp_path / "kb.yaml"
        kb.write_text("legal_provisions: []\n", encoding="utf-8")
        case = tmp_path / "c.yaml"
        case.write_text("cases: []\n", encoding="utf-8")
        for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
            if hasattr(KnowledgeFreshnessChecker, attr):
                delattr(KnowledgeFreshnessChecker, attr)
        c1 = KnowledgeFreshnessChecker(kb_path=str(kb), case_path=str(case))
        c1.provisions.append({"fake": True})
        c2 = KnowledgeFreshnessChecker(kb_path=str(kb), case_path=str(case))
        assert len(c2.provisions) == 1  # 使用了缓存

    def test_different_params_reloads(self, tmp_path):
        kb1 = tmp_path / "kb1.yaml"
        kb1.write_text(
            "legal_provisions:\n- law: A\n  article: 1\n  title: T\n  content: C\n  status: active\n", encoding="utf-8"
        )
        kb2 = tmp_path / "kb2.yaml"
        kb2.write_text("legal_provisions: []\n", encoding="utf-8")
        for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
            if hasattr(KnowledgeFreshnessChecker, attr):
                delattr(KnowledgeFreshnessChecker, attr)
        c1 = KnowledgeFreshnessChecker(kb_path=str(kb1))
        assert len(c1.provisions) == 1
        c2 = KnowledgeFreshnessChecker(kb_path=str(kb2))
        assert len(c2.provisions) == 0


class TestParseDate:
    def test_valid_date(self):
        assert KnowledgeFreshnessChecker._parse_date("2026-01-15") == date(2026, 1, 15)

    def test_none_returns_none(self):
        assert KnowledgeFreshnessChecker._parse_date(None) is None

    def test_empty_string(self):
        assert KnowledgeFreshnessChecker._parse_date("") is None

    def test_invalid_format(self):
        assert KnowledgeFreshnessChecker._parse_date("2026/01/15") is None

    def test_garbage(self):
        assert KnowledgeFreshnessChecker._parse_date("not-a-date") is None


class TestCheckAll:
    def test_counts_correct(self, checker):
        report = checker.check_all()
        assert report.total_provisions == 3
        assert report.total_cases == 1
        assert report.repealed_count == 1

    def test_repealed_warning(self, checker):
        report = checker.check_all()
        repealed = [w for w in report.warnings if w.status == LegalStatus.REPEALED]
        assert len(repealed) >= 1
        assert "担保法" in repealed[0].item_name
        assert all(w.severity == "critical" for w in repealed)

    def test_overall_status_critical(self, checker):
        report = checker.check_all()
        assert report.overall_status == "critical"  # 有废止法条

    def test_healthy_when_all_fresh(self, tmp_path):
        kb = tmp_path / "kb.yaml"
        today = date.today().strftime("%Y-%m-%d")
        kb.write_text(
            f"legal_provisions:\n- law: 测试法\n  article: 第1条\n  title: 测试\n"
            f"  content: 内容\n  status: active\n  last_verified: '{today}'\n",
            encoding="utf-8",
        )
        for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
            if hasattr(KnowledgeFreshnessChecker, attr):
                delattr(KnowledgeFreshnessChecker, attr)
        c = KnowledgeFreshnessChecker(kb_path=str(kb))
        report = c.check_all()
        assert report.overall_status == "healthy"


class TestCheckItemsReferenced:
    def test_finds_repealed(self, checker):
        warnings = checker.check_items_referenced(["《担保法》第8条"])
        assert any(w.status == LegalStatus.REPEALED for w in warnings)

    def test_no_match(self, checker):
        warnings = checker.check_items_referenced(["《不存在的法》第999条"])
        assert len(warnings) == 0


class TestYAMLErrorHandling:
    def test_invalid_yaml(self, tmp_path):
        kb = tmp_path / "bad.yaml"
        kb.write_text("{{invalid yaml", encoding="utf-8")
        for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
            if hasattr(KnowledgeFreshnessChecker, attr):
                delattr(KnowledgeFreshnessChecker, attr)
        c = KnowledgeFreshnessChecker(kb_path=str(kb))
        assert c.provisions == []

    def test_missing_file(self, tmp_path):
        for attr in ["_cache", "_cache_key", "_cached_provisions", "_cached_cases"]:
            if hasattr(KnowledgeFreshnessChecker, attr):
                delattr(KnowledgeFreshnessChecker, attr)
        c = KnowledgeFreshnessChecker(kb_path=str(tmp_path / "nonexistent.yaml"))
        assert c.provisions == []


class TestFormatAndDisclaimer:
    def test_format_report(self, checker):
        report = checker.check_all()
        text = checker.format_report_for_display(report)
        assert "知识库新鲜度报告" in text
        assert "法条总数" in text

    def test_disclaimer(self, checker):
        text = checker.get_freshness_disclaimer()
        assert "时效性声明" in text
        assert "国家法律法规数据库" in text
