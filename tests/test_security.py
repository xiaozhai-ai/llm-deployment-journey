"""SecurityPreprocessor 单元测试"""

import pytest

from src.security import SecurityPreprocessor


@pytest.fixture
def sp():
    return SecurityPreprocessor()


# ============================================
# 敏感信息检测
# ============================================


class TestDetectSensitiveInfo:
    def test_id_card_18_digits(self, sp):
        result = sp.check_text("合同编号持有人：110101199001011234")
        types = [item.type for item in result.sensitive_items]
        assert "身份证号" in types

    def test_id_card_ending_with_x(self, sp):
        result = sp.check_text("身份证：11010119900101123X")
        types = [item.type for item in result.sensitive_items]
        assert "身份证号" in types

    def test_phone_number(self, sp):
        result = sp.check_text("联系电话：13812345678")
        types = [item.type for item in result.sensitive_items]
        assert "手机号" in types

    def test_email(self, sp):
        result = sp.check_text("邮箱：test@example.com")
        types = [item.type for item in result.sensitive_items]
        assert "邮箱" in types

    def test_bank_card_16_digits(self, sp):
        # 使用 Luhn 校验有效的卡号
        result = sp.check_text("卡号：4532015112830366")
        types = [item.type for item in result.sensitive_items]
        assert "银行卡号" in types

    def test_bank_card_19_digits(self, sp):
        result = sp.check_text("卡号：622202123456123456789")
        # 长数字串可能同时匹配银行卡号和统一社会信用代码
        assert len(result.sensitive_items) > 0

    def test_no_sensitive_info(self, sp):
        result = sp.check_text("这是一份普通的合同文本，不含任何敏感信息。")
        assert len(result.sensitive_items) == 0

    def test_mixed_sensitive_info(self, sp):
        text = "甲方张三，身份证110101199001011234，手机13812345678，邮箱zhang@test.com"
        result = sp.check_text(text)
        types = {item.type for item in result.sensitive_items}
        assert "身份证号" in types
        assert "手机号" in types
        assert "邮箱" in types

    def test_empty_text(self, sp):
        result = sp.check_text("")
        assert len(result.sensitive_items) == 0
        assert not result.out_of_scope

    def test_no_false_positive_short_number(self, sp):
        result = sp.check_text("合同编号：2024-001，金额：1000元")
        id_items = [item for item in result.sensitive_items if item.type == "身份证号"]
        assert len(id_items) == 0


# ============================================
# 脱敏处理
# ============================================


class TestMaskSensitiveInfo:
    def test_mask_id_card(self, sp):
        text = "身份证：110101199001011234"
        masked, items = sp.mask_sensitive_info(text)
        assert "110101****1234" in masked
        assert "110101199001011234" not in masked

    def test_mask_phone(self, sp):
        text = "手机：13812345678"
        masked, items = sp.mask_sensitive_info(text)
        assert "138****5678" in masked
        assert "13812345678" not in masked

    def test_mask_email(self, sp):
        text = "邮箱：test@example.com"
        masked, items = sp.mask_sensitive_info(text)
        assert "te***@example.com" in masked
        assert "test@example.com" not in masked

    def test_mask_bank_card_16(self, sp):
        text = "卡号：4532015112830366"
        masked, items = sp.mask_sensitive_info(text)
        assert "4532****0366" in masked
        assert "4532015112830366" not in masked

    def test_mask_preserves_surrounding_text(self, sp):
        text = "甲方张三，手机13812345678，地址北京市"
        masked, items = sp.mask_sensitive_info(text)
        assert "甲方张三" in masked
        assert "地址北京市" in masked

    def test_mask_multiple_items_no_offset_error(self, sp):
        text = "身份证110101199001011234，手机13812345678"
        masked, items = sp.mask_sensitive_info(text)
        assert "110101199001011234" not in masked
        assert "13812345678" not in masked
        assert "****" in masked

    def test_mask_empty_text(self, sp):
        masked, items = sp.mask_sensitive_info("")
        assert masked == ""
        assert len(items) == 0

    def test_mask_no_sensitive_info(self, sp):
        text = "普通合同文本"
        masked, items = sp.mask_sensitive_info(text)
        assert masked == text
        assert len(items) == 0


# ============================================
# 越界检测
# ============================================


class TestOutOfScope:
    def test_criminal_keyword(self, sp):
        result = sp.check_text("本案涉及刑事犯罪行为")
        assert result.out_of_scope
        assert "刑事" in result.out_of_scope_reason or "犯罪" in result.out_of_scope_reason

    def test_prison_keyword(self, sp):
        result = sp.check_text("被告人被判处有期徒刑三年")
        assert result.out_of_scope

    def test_foreign_law(self, sp):
        # "境外法律" 已从范围检测中移除，常见于跨境合同不应拦截
        result = sp.check_text("本合同适用境外法律规定")
        assert not result.out_of_scope

    def test_ip_litigation(self, sp):
        # "知识产权诉讼" 已从范围检测中移除，常见于许可合同不应拦截
        result = sp.check_text("涉及知识产权诉讼案件")
        assert not result.out_of_scope

    def test_normal_contract(self, sp):
        result = sp.check_text("甲方应按约定时间支付货款，违约方承担违约责任。")
        assert not result.out_of_scope

    def test_no_out_of_scope_keyword(self, sp):
        result = sp.check_text("保密义务自合同签订之日起生效")
        assert not result.out_of_scope
        assert result.out_of_scope_reason is None

    def test_multiple_out_of_scope_keywords(self, sp):
        result = sp.check_text("涉及刑事犯罪和税务筹划")
        assert result.out_of_scope


# ============================================
# 风险提示
# ============================================


class TestRiskWarning:
    def test_warning_with_sensitive_info(self, sp):
        result = sp.check_text("手机13812345678，邮箱test@example.com")
        assert result.risk_warning is not None
        assert "手机号码" in result.risk_warning
        assert "电子邮箱" in result.risk_warning

    def test_warning_with_id_card(self, sp):
        result = sp.check_text("身份证110101199001011234")
        assert result.risk_warning is not None
        assert "身份证号码" in result.risk_warning

    def test_no_warning_without_sensitive_info(self, sp):
        result = sp.check_text("普通合同文本")
        assert result.risk_warning is None

    def test_warning_mentions_all_detected_types(self, sp):
        # 使用 Luhn 有效的银行卡号
        text = "身份证110101199001011234，手机13812345678，卡号4532015112830366"
        result = sp.check_text(text)
        assert result.risk_warning is not None
        assert "身份证号码" in result.risk_warning
        assert "手机号码" in result.risk_warning
        assert "银行卡号" in result.risk_warning


# ============================================
# 边界条件
# ============================================


class TestEdgeCases:
    def test_empty_string(self, sp):
        result = sp.check_text("")
        assert len(result.sensitive_items) == 0
        assert not result.out_of_scope
        assert result.risk_warning is None

    def test_only_whitespace(self, sp):
        result = sp.check_text("   \n\t  ")
        assert len(result.sensitive_items) == 0

    def test_long_text(self, sp):
        text = "普通文本" * 10000
        result = sp.check_text(text)
        assert len(result.sensitive_items) == 0

    def test_special_characters(self, sp):
        result = sp.check_text("合同金额：￥100,000.00（含税）")
        assert len(result.sensitive_items) == 0

    def test_unicode_text(self, sp):
        result = sp.check_text("本合同一式两份，甲乙双方各执一份。")
        assert not result.out_of_scope

    def test_id_card_at_text_boundary(self, sp):
        result = sp.check_text("110101199001011234")
        types = [item.type for item in result.sensitive_items]
        assert "身份证号" in types

    def test_phone_not_11_digits_rejected(self, sp):
        result = sp.check_text("电话：1381234567")
        phone_items = [item for item in result.sensitive_items if item.type == "手机号"]
        assert len(phone_items) == 0

    def test_phone_not_starting_with_1_rejected(self, sp):
        result = sp.check_text("电话：23812345678")
        phone_items = [item for item in result.sensitive_items if item.type == "手机号"]
        assert len(phone_items) == 0
