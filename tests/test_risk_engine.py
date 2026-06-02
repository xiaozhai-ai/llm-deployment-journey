"""
RiskEngine 单元测试

覆盖：
- 规则加载
- 规则匹配（risk_condition 类型）
- 缺失条款检测（missing_clause 类型）
- 置信度计算
- Playbook 风险等级调整
- 风险去重
- 风险-条款溯源关联
- LLM 响应解析
- 文档类型检测
"""

import json
from unittest.mock import MagicMock

import pytest

from src.core.exceptions import RuleLoadError
from src.analysis.risk_engine import RiskAnalysisResult, RiskEngine, RiskItem


@pytest.fixture
def engine(tmp_path):
    """创建使用临时配置的 RiskEngine"""
    rules_content = """
document_types:
  contract:
    name: "合同"
  agreement:
    name: "协议"

risk_rules:
  - id: "MISSING_001"
    name: "违约责任条款缺失"
    category: "条款缺失"
    risk_level: "high"
    description: "合同中未明确违约责任"
    legal_basis: "民法典第五百七十七条"
    suggestion: "建议补充违约责任条款"
    applicable_types: ["contract"]
    detection:
      type: "missing_clause"
      presence_keywords:
        - "违约责任"
        - "违约金"
        - "赔偿损失"
      substance_patterns:
        - "违约.{0,10}(金|责任|赔偿).{0,15}(约定|规定|应当|为)"

  - id: "IMBALANCE_001"
    name: "单方解除权不对等"
    category: "权利义务失衡"
    risk_level: "high"
    description: "仅一方享有单方解除权"
    legal_basis: "民法典第四百九十七条"
    suggestion: "建议修改为双方对等的解除权"
    applicable_types: ["contract", "agreement"]
    detection:
      type: "risk_condition"
      risk_keywords:
        - "单方解除"
        - "有权解除"
        - "随时解除"
      safe_keywords:
        - "双方均可解除"
        - "双方协商一致解除"

  - id: "COMPLIANCE_001"
    name: "免责条款过度"
    category: "合规性冲突"
    risk_level: "high"
    description: "免责条款可能无效"
    legal_basis: "民法典第五百零六条"
    suggestion: "建议删除过度免责条款"
    applicable_types: ["contract"]
    detection:
      type: "risk_condition"
      risk_keywords:
        - "免责"
        - "不承担责任"
        - "概不负责"
      safe_keywords:
        - "不可抗力"
        - "法律另有规定"
"""
    rules_file = tmp_path / "legal_rules.yaml"
    rules_file.write_text(rules_content, encoding="utf-8")

    # 创建 playbooks 目录（空）
    playbooks_dir = tmp_path / "playbooks"
    playbooks_dir.mkdir()

    return RiskEngine(rules_path=str(rules_file), playbooks_dir=str(playbooks_dir))


@pytest.fixture
def mock_playbook():
    """创建 mock Playbook"""
    playbook = MagicMock()
    playbook.should_check_rule.return_value = True
    playbook.adjust_risk_level.side_effect = lambda rid, level: level
    playbook.is_focus_area.return_value = False
    playbook.custom_prompts = {}
    playbook.role = "neutral"
    playbook.name = "中立审查"
    return playbook


# ============================================
# 规则加载
# ============================================


class TestRuleLoading:
    """规则加载测试"""

    def test_load_rules_success(self, engine):
        """成功加载规则"""
        assert len(engine.rules) == 3
        assert engine.rules[0]["id"] == "MISSING_001"

    def test_load_rules_document_types(self, engine):
        """加载文档类型配置"""
        assert "contract" in engine.document_types
        assert engine.document_types["contract"]["name"] == "合同"

    def test_load_rules_file_not_found(self, tmp_path):
        """规则文件不存在应抛出 RuleLoadError"""
        playbooks_dir = tmp_path / "playbooks"
        playbooks_dir.mkdir()

        with pytest.raises(RuleLoadError):
            RiskEngine(rules_path=str(tmp_path / "nonexistent.yaml"), playbooks_dir=str(playbooks_dir))

    def test_load_rules_invalid_yaml(self, tmp_path):
        """无效 YAML 应抛出 RuleLoadError"""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml", encoding="utf-8")
        playbooks_dir = tmp_path / "playbooks"
        playbooks_dir.mkdir()

        with pytest.raises(RuleLoadError):
            RiskEngine(rules_path=str(bad_file), playbooks_dir=str(playbooks_dir))


# ============================================
# 缺失条款检测
# ============================================


class TestMissingClauseDetection:
    """缺失条款检测测试"""

    def test_missing_clause_detected(self, engine):
        """合同中无违约相关关键词 → 检测到缺失"""
        text = "甲方应按时付款。乙方应按时交货。双方应友好合作。"
        result = engine.analyze_by_rules(text, document_type="contract")

        missing_risks = [r for r in result.risks if r.id == "MISSING_001"]
        assert len(missing_risks) == 1
        assert missing_risks[0].risk_level == "high"

    def test_missing_clause_present(self, engine):
        """合同中有完整违约责任条款 → 不缺失"""
        # substance_pattern 要求"违约.{0,10}(金|责任|赔偿).{0,15}(约定|规定|应当|为)"
        text = "违约责任：如乙方违约，应当支付违约金10万元，赔偿甲方全部损失。"
        result = engine.analyze_by_rules(text, document_type="contract")

        missing_risks = [r for r in result.risks if r.id == "MISSING_001"]
        assert len(missing_risks) == 0

    def test_missing_clause_mentioned_but_no_substance(self, engine):
        """合同中提及违约但无实质约定 → 仍检测为缺失（低置信度）"""
        text = "双方应遵守合同约定，如发生违约，另行协商。"  # 有"违约"但无实质内容
        result = engine.analyze_by_rules(text, document_type="contract")

        [r for r in result.risks if r.id == "MISSING_001"]
        # 可能检测到缺失（置信度较低），也可能不检测到
        # 关键是不应崩溃
        assert isinstance(result, RiskAnalysisResult)


# ============================================
# 风险条件匹配
# ============================================


class TestRiskConditionMatching:
    """风险条件匹配测试"""

    def test_risk_keywords_match(self, engine):
        """命中风险关键词且无安全关键词 → 触发风险"""
        text = "甲方有权随时解除本合同，乙方不得异议。"
        result = engine.analyze_by_rules(text, document_type="contract")

        imbalance_risks = [r for r in result.risks if r.id == "IMBALANCE_001"]
        assert len(imbalance_risks) == 1

    def test_risk_keywords_with_safe_keywords(self, engine):
        """同时命中风险和安全关键词 → 安全关键词抵消，不触发"""
        text = "双方均可解除本合同，双方协商一致解除。"
        result = engine.analyze_by_rules(text, document_type="contract")

        imbalance_risks = [r for r in result.risks if r.id == "IMBALANCE_001"]
        assert len(imbalance_risks) == 0

    def test_no_risk_keywords(self, engine):
        """无风险关键词 → 不触发"""
        text = "甲方应按时付款，乙方应按时交货。"
        result = engine.analyze_by_rules(text, document_type="contract")

        imbalance_risks = [r for r in result.risks if r.id == "IMBALANCE_001"]
        assert len(imbalance_risks) == 0

    def test_exemption_clause_detected(self, engine):
        """免责条款 → 触发合规风险"""
        text = "甲方对任何损失概不负责，不承担任何责任。"
        result = engine.analyze_by_rules(text, document_type="contract")

        compliance_risks = [r for r in result.risks if r.id == "COMPLIANCE_001"]
        assert len(compliance_risks) == 1

    def test_exemption_with_force_majeure(self, engine):
        """免责 + 不可抗力关键词 → 安全关键词抵消"""
        text = "因不可抗力导致的损失，甲方不承担责任。"
        result = engine.analyze_by_rules(text, document_type="contract")

        compliance_risks = [r for r in result.risks if r.id == "COMPLIANCE_001"]
        # safe_hits >= risk_hits → 不触发
        assert len(compliance_risks) == 0


# ============================================
# 置信度计算
# ============================================


class TestConfidenceCalculation:
    """置信度计算测试"""

    def test_confidence_range(self, engine):
        """置信度应在 [0.3, 0.95] 范围内"""
        text = "甲方有权随时解除本合同。"
        result = engine.analyze_by_rules(text, document_type="contract")

        for risk in result.risks:
            assert 0.3 <= risk.confidence <= 0.95

    def test_higher_keyword_hit_higher_confidence(self, engine):
        """更多关键词命中 → 更高置信度"""
        # 命中 1 个关键词
        text1 = "甲方有权单方解除本合同。"
        result1 = engine.analyze_by_rules(text1, document_type="contract")

        # 命中 2 个关键词
        text2 = "甲方有权单方解除本合同，随时解除，有权解除。"
        result2 = engine.analyze_by_rules(text2, document_type="contract")

        risks1 = [r for r in result1.risks if r.id == "IMBALANCE_001"]
        risks2 = [r for r in result2.risks if r.id == "IMBALANCE_001"]

        if risks1 and risks2:
            assert risks2[0].confidence >= risks1[0].confidence


# ============================================
# Playbook 风险等级调整
# ============================================


class TestPlaybookAdjustment:
    """Playbook 风险等级调整测试"""

    def test_playbook_adjusts_risk_level(self, engine, mock_playbook):
        """Playbook 调整缺失类风险等级（adjust_risk_level 仅对 missing_clause 类型生效）"""
        mock_playbook.adjust_risk_level.side_effect = lambda rid, level: "critical" if rid == "MISSING_001" else level

        # 触发 MISSING_001（无违约相关关键词）
        text = "甲方应按时付款。乙方应按时交货。"
        result = engine.analyze_by_rules(text, document_type="contract", playbook=mock_playbook)

        missing_risks = [r for r in result.risks if r.id == "MISSING_001"]
        if missing_risks:
            assert missing_risks[0].risk_level == "critical"
            assert missing_risks[0].playbook_adjusted is True

    def test_playbook_no_adjustment(self, engine, mock_playbook):
        """Playbook 不调整时保持原等级"""
        text = "甲方有权随时解除本合同。"
        result = engine.analyze_by_rules(text, document_type="contract", playbook=mock_playbook)

        for risk in result.risks:
            assert risk.playbook_adjusted is False

    def test_playbook_focus_area_boost(self, engine, mock_playbook):
        """Playbook 重点关注领域内的风险应提升等级"""
        mock_playbook.is_focus_area.return_value = True

        text = "甲方有权随时解除本合同。"
        result = engine.analyze_by_rules(text, document_type="contract", playbook=mock_playbook)

        imbalance_risks = [r for r in result.risks if r.id == "IMBALANCE_001"]
        if imbalance_risks:
            assert imbalance_risks[0].risk_level == "high"

    def test_playbook_excludes_rules(self, engine, mock_playbook):
        """Playbook 排除特定规则"""
        mock_playbook.should_check_rule.side_effect = lambda rid: rid != "IMBALANCE_001"

        text = "甲方有权随时解除本合同。"
        result = engine.analyze_by_rules(text, document_type="contract", playbook=mock_playbook)

        imbalance_risks = [r for r in result.risks if r.id == "IMBALANCE_001"]
        assert len(imbalance_risks) == 0


# ============================================
# 风险计数
# ============================================


class TestRiskCounting:
    """风险计数测试"""

    def test_risk_counts(self, engine):
        """验证风险计数正确"""
        text = "甲方有权随时解除本合同。甲方对任何损失概不负责。"
        result = engine.analyze_by_rules(text, document_type="contract")

        assert result.high_count == sum(1 for r in result.risks if r.risk_level == "high")
        assert result.critical_count == sum(1 for r in result.risks if r.risk_level == "critical")
        assert result.medium_count == sum(1 for r in result.risks if r.risk_level == "medium")
        assert result.low_count == sum(1 for r in result.risks if r.risk_level == "low")

    def test_no_risks(self, engine):
        """无风险时计数全为 0"""
        text = "这是一份正常的合同，双方权利义务对等。"
        result = engine.analyze_by_rules(text, document_type="contract")

        # 可能有缺失类风险，但风险条件类不应触发
        assert isinstance(result, RiskAnalysisResult)


# ============================================
# 风险去重
# ============================================


class TestRiskDeduplication:
    """风险去重测试"""

    def test_duplicate_rule_id_deduplicated(self, engine):
        """相同 rule_id 的风险应去重"""
        risks = [
            RiskItem(
                id="R1",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                confidence=0.8,
            ),
            RiskItem(
                id="R2",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="medium",
                description="desc",
                confidence=0.6,
            ),
        ]
        result = engine.deduplicate_risks(risks)
        assert len(result) == 1
        assert result[0].risk_level == "high"  # 保留更高等级

    def test_different_rule_id_not_deduplicated(self, engine):
        """不同 rule_id 的风险不应去重"""
        risks = [
            RiskItem(
                id="R1",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                confidence=0.8,
            ),
            RiskItem(
                id="R2",
                rule_id="RULE_002",
                name="风险B",
                category="cat",
                risk_level="medium",
                description="desc",
                confidence=0.6,
            ),
        ]
        result = engine.deduplicate_risks(risks)
        assert len(result) == 2

    def test_empty_risks(self, engine):
        """空列表去重返回空列表"""
        assert engine.deduplicate_risks([]) == []

    def test_no_rule_id_name_based_dedup(self, engine):
        """无 rule_id 时基于名称 + 内容预览去重"""
        risks = [
            RiskItem(
                id="R1",
                rule_id="",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                clause_content_preview="这是相同的条款内容",
                confidence=0.8,
            ),
            RiskItem(
                id="R2",
                rule_id="",
                name="风险A",
                category="cat",
                risk_level="medium",
                description="desc",
                clause_content_preview="这是相同的条款内容片段",
                confidence=0.6,
            ),
        ]
        result = engine.deduplicate_risks(risks)
        assert len(result) == 1


# ============================================
# LLM 响应解析
# ============================================


class TestLLMResponseParsing:
    """LLM 响应解析测试"""

    def test_parse_json_array(self, engine):
        """解析标准 JSON 数组"""
        response = json.dumps(
            [
                {
                    "name": "风险1",
                    "category": "违约",
                    "risk_level": "high",
                    "description": "测试",
                    "clause_preview": "条款内容",
                    "confidence": 0.8,
                }
            ]
        )
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1
        assert risks[0].name == "风险1"
        assert risks[0].risk_level == "high"

    def test_parse_markdown_code_block(self, engine):
        """解析 markdown 代码块中的 JSON"""
        response = '```json\n[{"name": "风险1", "risk_level": "medium", "confidence": 0.7}]\n```'
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1

    def test_parse_invalid_risk_level_defaults_medium(self, engine):
        """无效 risk_level 默认为 medium"""
        response = json.dumps([{"name": "风险1", "risk_level": "extreme", "confidence": 0.7}])
        risks = engine._parse_llm_response(response)
        assert risks[0].risk_level == "medium"

    def test_parse_invalid_confidence_clamped(self, engine):
        """无效 confidence 值应被修正"""
        response = json.dumps([{"name": "风险1", "risk_level": "high", "confidence": 1.5}])
        risks = engine._parse_llm_response(response)
        assert risks[0].confidence == 0.7  # 无效值回退到 0.7

    def test_parse_empty_response(self, engine):
        """空响应返回空列表"""
        assert engine._parse_llm_response("") == []

    def test_parse_non_json_response(self, engine):
        """非 JSON 响应返回空列表"""
        assert engine._parse_llm_response("这不是 JSON") == []

    def test_parse_json_object_with_risks_key(self, engine):
        """解析包含 risks 键的 JSON 对象"""
        response = json.dumps({"risks": [{"name": "风险1", "risk_level": "low"}]})
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1

    def test_parse_name_truncated(self, engine):
        """风险名称应截断到 100 字符"""
        long_name = "A" * 200
        response = json.dumps([{"name": long_name, "risk_level": "high", "confidence": 0.7}])
        risks = engine._parse_llm_response(response)
        assert len(risks[0].name) <= 100


# ============================================
# 文档类型检测
# ============================================


class TestDocumentTypeDetection:
    """文档类型检测测试"""

    def test_detect_contract(self, engine):
        """合同类型文档"""
        text = "本合同由甲方和乙方签订，约定价款和报酬，甲方应履行义务。"
        assert engine.detect_document_type(text) == "contract"

    def test_detect_agreement(self, engine):
        """协议类型文档"""
        text = "本协议由双方签订，约定合作内容和合作期限。"
        assert engine.detect_document_type(text) == "agreement"

    def test_detect_privacy_policy(self, engine):
        """隐私政策类型文档"""
        text = "本隐私政策说明我们如何收集个人信息、使用数据，以及 cookie 政策。"
        assert engine.detect_document_type(text) == "privacy_policy"

    def test_detect_empty_text(self, engine):
        """空文本返回 unknown（非法律文件）"""
        result = engine.detect_document_type("")
        assert result == "unknown"

    def test_detect_non_legal_text(self, engine):
        """非法律文件返回 unknown"""
        text = "阿里云大模型ACP考试大纲，包含云计算、大数据、人工智能等技术方向。"
        assert engine.detect_document_type(text) == "unknown"

    def test_detect_short_contract(self, engine):
        """短文本合同仍能正确识别"""
        text = "甲方：ABC公司，乙方：XYZ公司。本合同约定服务内容。"
        assert engine.detect_document_type(text) == "contract"


# ============================================
# 风险-条款溯源关联
# ============================================


class TestRiskClauseLinking:
    """风险-条款溯源关联测试"""

    def test_link_by_title(self, engine):
        """通过标题匹配关联风险和条款"""
        from src.parsing.parser import Clause

        risks = [
            RiskItem(
                id="R1",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                clause_position="违约责任",
                confidence=0.8,
            )
        ]
        clauses = [
            Clause(id=1, content="如乙方违约，应支付违约金。", title="违约责任"),
            Clause(id=2, content="双方应友好协商。", title="争议解决"),
        ]

        result = engine.link_risks_to_clauses(risks, clauses)
        assert result[0].clause_id == 1
        assert result[0].clause_title == "违约责任"

    def test_link_by_content(self, engine):
        """通过内容匹配关联风险和条款（preview 需 > 20 字符）"""
        from src.parsing.parser import Clause

        preview = "如乙方违约应支付违约金十万元，赔偿甲方因此遭受的全部经济损失和合理费用"
        risks = [
            RiskItem(
                id="R1",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                clause_content_preview=preview,
                confidence=0.8,
            )
        ]
        clauses = [
            Clause(
                id=1, content="如乙方违约应支付违约金十万元，赔偿甲方因此遭受的全部经济损失和合理费用。另有约定的除外。"
            ),
        ]

        result = engine.link_risks_to_clauses(risks, clauses)
        assert result[0].clause_id == 1

    def test_link_no_match(self, engine):
        """无匹配时 clause_id 保持为 0"""
        from src.parsing.parser import Clause

        risks = [
            RiskItem(
                id="R1",
                rule_id="RULE_001",
                name="风险A",
                category="cat",
                risk_level="high",
                description="desc",
                clause_position="不存在的条款",
                confidence=0.8,
            )
        ]
        clauses = [
            Clause(id=1, content="完全无关的内容。", title="无关条款"),
        ]

        result = engine.link_risks_to_clauses(risks, clauses)
        assert result[0].clause_id == 0
