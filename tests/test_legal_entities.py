"""法律实体提取测试"""

import pytest


class TestExtractMetadata:
    """合同元数据提取测试"""

    def test_extract_contract_name(self):
        from src.legal_entities.metadata import extract_metadata

        text = """
        采购合同
        合同编号：CG-2024-001
        
        甲方：北京科技有限公司
        乙方：上海贸易有限公司
        """
        result = extract_metadata(text)
        assert result.contract_name == "采购合同"

    def test_extract_parties(self):
        from src.legal_entities.metadata import extract_metadata

        text = """
        甲方：北京科技有限公司
        乙方：上海贸易有限公司
        """
        result = extract_metadata(text)
        assert len(result.parties) == 2
        assert result.parties[0].name == "北京科技有限公司"
        assert result.parties[0].role == "甲方"

    def test_extract_dispute_resolution(self):
        from src.legal_entities.metadata import extract_metadata

        text = "因本合同引起的争议，双方同意提交北京仲裁委员会仲裁。"
        result = extract_metadata(text)
        assert result.dispute_resolution is not None
        assert "仲裁" in result.dispute_resolution

    def test_extract_governing_law(self):
        from src.legal_entities.metadata import extract_metadata

        text = "本合同的签订、履行、解释及争议解决均适用中华人民共和国法律。"
        result = extract_metadata(text)
        assert result.governing_law is not None
        assert "中华人民共和国" in result.governing_law


class TestExtractAmounts:
    """金额实体提取测试"""

    def test_extract_arabic_amount(self):
        from src.legal_entities.amount import extract_amounts

        text = "合同总价款为人民币500万元整。"
        amounts = extract_amounts(text)
        assert len(amounts) >= 1
        assert amounts[0].amount == 5000000.0

    def test_extract_chinese_uppercase(self):
        from src.legal_entities.amount import extract_amounts

        text = "合同总价款为人民币伍佰万元整。"
        amounts = extract_amounts(text)
        assert len(amounts) >= 1
        assert amounts[0].amount == 5000000.0

    def test_paired_amounts(self):
        from src.legal_entities.amount import extract_amounts

        text = "合同总价款为500万元（大写：伍佰万元整）。"
        amounts = extract_amounts(text)
        # 应该有配对标记
        pair_ids = [a.pair_id for a in amounts if a.pair_id]
        assert len(pair_ids) >= 1

    def test_check_consistency(self):
        from src.data_models import MoneyAmount
        from src.legal_entities.amount import check_amount_consistency

        amounts = [
            MoneyAmount(raw_text="500万元", amount=5000000.0, currency="CNY",
                        uppercase_text="伍佰万元整", lowercase_text="500万元", pair_id="pair_1"),
            MoneyAmount(raw_text="伍佰万元整", amount=5000000.0, currency="CNY",
                        uppercase_text="伍佰万元整", lowercase_text="500万元", pair_id="pair_1"),
        ]
        result = check_amount_consistency(amounts)
        assert all(a.is_consistent for a in result)

    def test_check_inconsistency(self):
        from src.data_models import MoneyAmount
        from src.legal_entities.amount import check_amount_consistency

        amounts = [
            MoneyAmount(raw_text="500万元", amount=5000000.0, currency="CNY",
                        uppercase_text="伍佰万元整", lowercase_text="400万元", pair_id="pair_1"),
        ]
        result = check_amount_consistency(amounts)
        assert result[0].is_consistent is False


class TestExtractDates:
    """日期实体提取测试"""

    def test_extract_cn_date(self):
        from src.legal_entities.date_extractor import extract_dates

        text = "本合同签订日期为2024年1月15日。"
        dates = extract_dates(text)
        assert len(dates) >= 1
        assert dates[0].date == "2024-01-15"

    def test_extract_iso_date(self):
        from src.legal_entities.date_extractor import extract_dates

        text = "交货日期：2024-03-20"
        dates = extract_dates(text)
        assert len(dates) >= 1
        assert dates[0].date == "2024-03-20"

    def test_detect_date_role(self):
        from src.legal_entities.date_extractor import extract_dates

        text = "本合同的生效日期为2024年1月1日，届满日为2025年12月31日。"
        dates = extract_dates(text)
        roles = [d.role for d in dates if d.role]
        assert any("生效" in (r or "") for r in roles)

    def test_relative_date(self):
        from src.legal_entities.date_extractor import extract_dates

        text = "自合同签订之日起30日内完成交货。"
        dates = extract_dates(text)
        assert any(d.date.startswith("relative:") for d in dates)
