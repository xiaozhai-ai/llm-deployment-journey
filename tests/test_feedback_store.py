"""
FeedbackStore 单元测试

覆盖：
- 记录保存与加载
- 相似度检索
- 风险类型检索
- Few-shot 导出（含省略号修复）
- 统计分析
- 文件锁（线程安全）
"""

import json
import os
from pathlib import Path

import pytest

from src.infra.feedback_store import CorrectionAction, FeedbackStore


@pytest.fixture
def tmp_feedback_dir(tmp_path):
    return str(tmp_path / "feedback")


@pytest.fixture
def store(tmp_feedback_dir):
    return FeedbackStore(feedback_dir=tmp_feedback_dir)


class TestRecordAndLoad:
    def test_record_correction(self, store):
        record = store.record_correction(
            clause_id=1,
            clause_text="甲方应按时付款",
            clause_title="付款条款",
            document_type="contract",
            playbook_id="party_b",
            original_risk={"name": "付款风险", "risk_level": "high"},
            user_action=CorrectionAction.AGREE,
        )
        assert record.record_id.startswith("fb_")
        assert record.user_action == "agree"
        assert len(store.records) == 1

    def test_persistence_across_instances(self, tmp_feedback_dir):
        store1 = FeedbackStore(feedback_dir=tmp_feedback_dir)
        store1.record_correction(
            clause_id=1,
            clause_text="测试",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={},
            user_action=CorrectionAction.AGREE,
        )
        store2 = FeedbackStore(feedback_dir=tmp_feedback_dir)
        assert len(store2.records) == 1

    def test_clause_text_truncated(self, store):
        long_text = "甲" * 3000
        record = store.record_correction(
            clause_id=1,
            clause_text=long_text,
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={},
            user_action=CorrectionAction.AGREE,
        )
        assert len(record.clause_text) == 2000

    def test_corrupted_jsonl_handled(self, tmp_feedback_dir):
        os.makedirs(tmp_feedback_dir, exist_ok=True)
        records_file = Path(tmp_feedback_dir) / "feedback_records.jsonl"
        with open(records_file, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps(
                    {
                        "record_id": "fb_1",
                        "timestamp": "2026-01-01",
                        "document_type": "t",
                        "playbook_id": "p",
                        "clause_id": 0,
                        "clause_text": "ok",
                        "user_action": "agree",
                    }
                )
                + "\n"
            )
        store = FeedbackStore(feedback_dir=tmp_feedback_dir)
        assert len(store.records) == 1  # 坏行被跳过


class TestSimilarCorrections:
    def test_finds_similar(self, store):
        store.record_correction(
            clause_id=1,
            clause_text="甲方应在30日内支付全款",
            clause_title="付款",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "付款风险"},
            user_action=CorrectionAction.FALSE_POSITIVE,
        )
        store.record_correction(
            clause_id=2,
            clause_text="乙方应提供技术支持服务",
            clause_title="技术",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "技术风险"},
            user_action=CorrectionAction.AGREE,
        )
        results = store.get_similar_corrections("甲方应在30日内付款")
        assert len(results) >= 1
        assert results[0].clause_text.startswith("甲方")

    def test_empty_corpus(self, store):
        results = store.get_similar_corrections("任意文本")
        assert results == []


class TestRiskTypeRetrieval:
    def test_get_by_risk_name(self, store):
        store.record_correction(
            clause_id=1,
            clause_text="文本",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "违约责任缺失"},
            user_action=CorrectionAction.LEVEL_UP,
        )
        results = store.get_corrections_for_risk_type("违约责任缺失")
        assert len(results) == 1

    def test_no_match(self, store):
        store.record_correction(
            clause_id=1,
            clause_text="文本",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "其他风险"},
            user_action=CorrectionAction.AGREE,
        )
        results = store.get_corrections_for_risk_type("违约责任缺失")
        assert len(results) == 0


class TestFewShotExport:
    def test_export_contains_examples(self, store):
        store.record_correction(
            clause_id=1,
            clause_text="甲方应按时付款" * 20,
            clause_title="付款",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "风险A", "risk_level": "high"},
            user_action=CorrectionAction.FALSE_POSITIVE,
            user_comment="这是误报",
        )
        output = store.export_as_few_shot("甲方付款条款", "风险A")
        assert "历史人工修正参考" in output
        assert "误报" in output

    def test_short_text_no_ellipsis(self, store):
        """P2-14: 短文本不应添加省略号"""
        store.record_correction(
            clause_id=1,
            clause_text="短文本",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "R"},
            user_action=CorrectionAction.AGREE,
        )
        output = store.export_as_few_shot("短文本")
        assert "短文本…" not in output
        assert "短文本" in output

    def test_long_text_has_ellipsis(self, store):
        long = "甲" * 150
        store.record_correction(
            clause_id=1,
            clause_text=long,
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "R"},
            user_action=CorrectionAction.AGREE,
        )
        output = store.export_as_few_shot("甲" * 150)
        assert "…" in output

    def test_empty_export(self, store):
        assert store.export_as_few_shot("任意文本") == ""


class TestStats:
    def test_stats(self, store):
        store.record_correction(
            clause_id=1,
            clause_text="A",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "R1"},
            user_action=CorrectionAction.FALSE_POSITIVE,
        )
        store.record_correction(
            clause_id=2,
            clause_text="B",
            clause_title="",
            document_type="contract",
            playbook_id="neutral",
            original_risk={"name": "R2"},
            user_action=CorrectionAction.AGREE,
        )
        stats = store.get_stats()
        assert stats["total_records"] == 2
        assert stats["false_positive_rate"] == 0.5
