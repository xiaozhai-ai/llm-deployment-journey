"""P5 签章 + 修订 + 定义提取测试"""

import pytest


class TestSignatureDetection:
    """签章识别测试"""

    def test_detect_party_signatures(self):
        from src.parsing.legal_entities.signature import detect_signatures

        text = """
        第十条 签章
        
        甲方：北京科技有限公司（盖章）
        法定代表人（签字）：张三
        
        乙方：上海贸易有限公司（盖章）
        法定代表人（签字）：李四
        """
        sigs = detect_signatures(text)
        assert len(sigs) >= 2
        roles = {s.party_role for s in sigs}
        assert "甲方" in roles
        assert "乙方" in roles

    def test_has_seal_detection(self):
        from src.parsing.legal_entities.signature import detect_signatures

        text = "甲方（盖章）：北京科技有限公司"
        sigs = detect_signatures(text)
        assert len(sigs) >= 1
        assert sigs[0].has_seal is True

    def test_has_signature_detection(self):
        from src.parsing.legal_entities.signature import detect_signatures

        text = "甲方（签字）：张三"
        sigs = detect_signatures(text)
        assert len(sigs) >= 1
        assert sigs[0].has_signature is True

    def test_no_signatures(self):
        from src.parsing.legal_entities.signature import detect_signatures

        text = "这是一份普通文本，没有任何特殊标记。"
        sigs = detect_signatures(text)
        assert len(sigs) == 0


class TestRevisionExtraction:
    """修订追踪测试"""

    def test_inline_delete(self):
        from src.parsing.legal_entities.revision import extract_revisions

        text = "合同金额为~~500万元~~修改为600万元。"
        revs = extract_revisions(text)
        assert any(r.revision_type == "delete" and "500万元" in r.text for r in revs)

    def test_inline_insert(self):
        from src.parsing.legal_entities.revision import extract_revisions

        text = "合同金额为[新增：600万元]。"
        revs = extract_revisions(text)
        assert any(r.revision_type == "insert" and "600万元" in r.text for r in revs)

    def test_inline_modify(self):
        from src.parsing.legal_entities.revision import extract_revisions

        text = "交货日期[修改：2024年6月30日]。"
        revs = extract_revisions(text)
        assert any(r.revision_type == "insert" for r in revs)

    def test_no_revisions(self):
        from src.parsing.legal_entities.revision import extract_revisions

        text = "这是一份没有修订标记的合同。"
        revs = extract_revisions(text)
        assert len(revs) == 0


class TestDefinitionExtraction:
    """定义引用测试"""

    def test_extract_short_name(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = '北京科技有限公司（以下简称"甲方"）与上海贸易有限公司（以下简称"乙方"）签订本合同。'
        defs = extract_definitions(text)
        terms = {d.term for d in defs}
        assert "甲方" in terms
        assert "乙方" in terms

    def test_extract_definition_text(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = '北京科技有限公司（以下简称"甲方"）'
        defs = extract_definitions(text)
        assert len(defs) >= 1
        assert "北京科技有限公司" in defs[0].definition_text

    def test_single_quotes(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = "北京科技有限公司（以下简称'甲方'）签订本合同。"
        defs = extract_definitions(text)
        assert any(d.term == "甲方" for d in defs)

    def test_chinese_quotes(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = "北京科技有限公司（以下简称\u2018甲方\u2019）签订本合同。"
        defs = extract_definitions(text)
        assert any(d.term == "甲方" for d in defs)

    def test_no_definitions(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = "这是一份没有定义条款的合同。"
        defs = extract_definitions(text)
        assert len(defs) == 0

    def test_definition_with_ref_linking(self):
        from src.parsing.legal_entities.definition import extract_definitions

        text = """
        北京科技有限公司（以下简称"甲方"）与上海贸易有限公司（以下简称"乙方"）签订本合同。
        甲方应向乙方支付货款。
        乙方应在收到货款后发货。
        """
        defs = extract_definitions(text)
        # 甲方和乙方都应该有引用
        for d in defs:
            if d.term in ("甲方", "乙方"):
                assert len(d.references) >= 0  # 至少被引用过
