"""
分析引擎层增强测试

覆盖本轮审查修复的 12 项问题：
- extract_json 公共函数（对象/数组/嵌套/markdown代码块）
- detect_document_type 代码信号误伤修复
- _parse_llm_response 复用 extract_json
- deduplicate_risks 无循环内导入
- _keyword_fallback 法律术语扩展查询
- Playbook 同 ID 覆盖警告
- _find_matching_clause 常量引用
- max_segments 可配置
- 截断日志
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analysis.risk_engine import RiskEngine, RiskItem
from src.infra.utils import extract_json, extract_json_object

# ============================================
# Fixtures
# ============================================

@pytest.fixture
def engine(tmp_path):
    """创建使用临时配置的 RiskEngine"""
    rules_content = """
document_types:
  contract:
    name: "合同"

risk_rules:
  - id: "TEST_001"
    name: "测试规则"
    category: "测试"
    risk_level: "medium"
    description: "测试规则描述"
    applicable_types: ["contract"]
    detection:
      type: "risk_condition"
      risk_keywords:
        - "测试"
      safe_keywords: []
"""
    rules_file = tmp_path / "legal_rules.yaml"
    rules_file.write_text(rules_content, encoding="utf-8")

    playbooks_dir = tmp_path / "playbooks"
    playbooks_dir.mkdir()

    return RiskEngine(rules_path=str(rules_file), playbooks_dir=str(playbooks_dir))


@pytest.fixture
def matcher(tmp_path):
    """创建 LegalMatcher 实例"""
    from src.analysis.legal_matcher import LegalMatcher

    kb_content = """
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
"""
    kb_path = tmp_path / "legal_kb.yaml"
    kb_path.write_text(kb_content, encoding="utf-8")

    mock_vs = MagicMock()
    mock_vs.hybrid_search.return_value = []
    return LegalMatcher(kb_path=str(kb_path), vector_store=mock_vs)


# ============================================
# extract_json 公共函数
# ============================================


class TestExtractJson:
    """extract_json 函数测试"""

    def test_plain_array(self):
        """纯 JSON 数组"""
        text = 'some text [{"name": "test"}] more text'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_plain_object(self):
        """纯 JSON 对象"""
        text = 'prefix {"key": "value"} suffix'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data == {"key": "value"}

    def test_markdown_fence_array(self):
        """markdown 代码块中的数组"""
        text = '```json\n[{"risk_level": "high"}]\n```'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert isinstance(data, list)

    def test_markdown_fence_object(self):
        """markdown 代码块中的对象"""
        text = '```json\n{"risks": [{"name": "r1"}]}\n```'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert "risks" in data

    def test_markdown_fence_no_lang(self):
        """无语言标记的代码块"""
        text = '```\n[1, 2, 3]\n```'
        result = extract_json(text)
        assert result is not None
        assert json.loads(result) == [1, 2, 3]

    def test_nested_object_in_array(self):
        """嵌套对象数组"""
        text = json.dumps([{"name": "r1", "details": {"level": "high", "tags": ["a", "b"]}}])
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data[0]["details"]["tags"] == ["a", "b"]

    def test_nested_array_in_object(self):
        """嵌套数组对象"""
        text = json.dumps({"risks": [{"name": "r1"}, {"name": "r2"}]})
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert len(data["risks"]) == 2

    def test_no_json_returns_none(self):
        """无 JSON 内容返回 None"""
        assert extract_json("no json here") is None

    def test_empty_string_returns_none(self):
        """空字符串返回 None"""
        assert extract_json("") is None

    def test_invalid_json_returns_none(self):
        """无效 JSON 返回 None"""
        assert extract_json("{not valid json]") is None

    def test_array_before_object(self):
        """数组在对象之前时，提取数组"""
        text = 'prefix [1, 2] {"key": "val"}'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data == [1, 2]

    def test_object_before_array(self):
        """对象在数组之前时，提取对象"""
        text = 'prefix {"key": "val"} [1, 2]'
        result = extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data == {"key": "val"}


class TestExtractJsonObjectCompat:
    """extract_json_object 向后兼容测试"""

    def test_returns_object(self):
        result = extract_json_object('{"key": "value"}')
        assert result is not None
        assert json.loads(result) == {"key": "value"}

    def test_returns_none_for_array(self):
        result = extract_json_object("[1, 2, 3]")
        assert result is None

    def test_returns_none_for_no_json(self):
        assert extract_json_object("no json") is None


# ============================================
# detect_document_type 代码信号误伤修复
# ============================================


class TestDocumentTypeCodeSignal:
    """代码信号不应误伤中文法律文本"""

    def test_import_in_chinese_text(self, engine):
        """含"进口"的中文合同不应被代码信号误伤"""
        text = (
            "本合同约定甲方进口货物的检验标准和付款方式。"
            "甲方应在收到货物后七日内完成验收。乙方应提供合格证明。"
        )
        assert engine.detect_document_type(text) == "contract"

    def test_from_in_chinese_text(self, engine):
        """含"从而"的中文文本不应被代码信号误伤"""
        text = (
            "甲方应按照约定提供服务，从而确保项目按时完成。"
            "双方应遵守合同约定的保密义务和知识产权条款。"
        )
        assert engine.detect_document_type(text) == "contract"

    def test_config_in_chinese_text(self, engine):
        """含"配置"的中文合同不应被代码信号误伤"""
        text = (
            "甲方负责系统配置和设备安装。"
            "合同约定配置标准应符合行业规范。"
            "违约责任和赔偿损失按照本合同约定执行。"
        )
        assert engine.detect_document_type(text) == "contract"

    def test_actual_code_still_detected(self, engine):
        """真正的代码仍然被正确识别为 unknown"""
        text = """
import os
import sys
from pathlib import Path
def main():
    config = {"key": "value"}
    try:
        result = process(config)
    except Exception as e:
        raise e
    return result
"""
        assert engine.detect_document_type(text) == "unknown"


# ============================================
# _parse_llm_response 复用 extract_json
# ============================================


class TestParseLLMResponseRefactored:
    """重构后的 _parse_llm_response 测试"""

    def test_markdown_fence_with_nested_json(self, engine):
        """markdown 代码块中嵌套 JSON 应正确解析"""
        response = '```json\n[{"name": "风险1", "risk_level": "high", "details": {"clause": "test"}, "confidence": 0.8}]\n```'
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1
        assert risks[0].name == "风险1"

    def test_text_surrounding_json(self, engine):
        """JSON 前后有文本时仍能提取"""
        response = '分析结果如下：\n[{"name": "违约风险", "risk_level": "medium", "confidence": 0.6}]\n以上为分析结果。'
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1
        assert risks[0].name == "违约风险"

    def test_object_with_risks_key(self, engine):
        """对象格式 {"risks": [...]} """
        response = json.dumps({"risks": [{"name": "r1", "risk_level": "low", "confidence": 0.5}]})
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1

    def test_single_object_not_in_array(self, engine):
        """单个对象（非数组）"""
        response = json.dumps({"name": "单个风险", "risk_level": "high", "confidence": 0.9})
        risks = engine._parse_llm_response(response)
        assert len(risks) == 1
        assert risks[0].name == "单个风险"


# ============================================
# _find_matching_clause 常量引用
# ============================================


class TestClauseMatchConstants:
    """条款匹配常量测试"""

    def test_constants_exist(self):
        """常量应定义在类上"""
        assert hasattr(RiskEngine, "CLAUSE_MATCH_PREFIX_LEN")
        assert hasattr(RiskEngine, "CLAUSE_MATCH_CONTAINS_LEN")
        assert RiskEngine.CLAUSE_MATCH_PREFIX_LEN == 80
        assert RiskEngine.CLAUSE_MATCH_CONTAINS_LEN == 100

    def test_constants_used_in_matching(self, engine):
        """常量应被 _find_matching_clause 使用"""
        import inspect

        source = inspect.getsource(engine._find_matching_clause)
        assert "self.CLAUSE_MATCH_PREFIX_LEN" in source
        assert "self.CLAUSE_MATCH_CONTAINS_LEN" in source


# ============================================
# max_segments 可配置
# ============================================


class TestMaxSegmentsConfig:
    """max_segments 可配置测试"""

    def test_default_constants(self):
        """默认常量值"""
        assert RiskEngine.DEFAULT_MAX_SEGMENT_LENGTH == 5000
        assert RiskEngine.DEFAULT_MAX_SEGMENTS == 3

    def test_analyze_with_llm_accepts_max_segments(self, engine):
        """analyze_with_llm 应接受 max_segments 参数"""
        import inspect

        sig = inspect.signature(engine.analyze_with_llm)
        assert "max_segments" in sig.parameters


# ============================================
# _keyword_fallback 法律术语扩展查询
# ============================================


class TestKeywordFallbackExpansion:
    """关键词回退检索的法律术语扩展测试"""

    def test_expansion_finds_synonym(self, matcher):
        """扩展查询应找到同义词对应的法条"""
        matches = matcher._keyword_fallback("违约赔偿金", "合同法", exclude_ids=set())
        assert len(matches) >= 1

    def test_expansion_respects_related_are_different(self):
        """related_are_different=True 的术语不应扩展 related 词"""
        from src.analysis.legal_terms import expand_query

        expanded = expand_query("订金")
        assert "订金" in expanded
        assert "预付款" in expanded
        assert "定金" not in expanded


# ============================================
# Playbook 同 ID 覆盖警告
# ============================================


class TestPlaybookDuplicateWarning:
    """Playbook 同 ID 覆盖应产生警告"""

    def test_override_builtin_warns(self, tmp_path):
        """自定义 playbook 覆盖内置策略时应有警告"""
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "neutral.yaml").write_text(
            "id: neutral\nname: 自定义中立\nstrictness: high\n",
            encoding="utf-8",
        )

        with patch("src.analysis.playbook_manager.logger_manager") as mock_logger:
            from src.analysis.playbook_manager import PlaybookManager

            PlaybookManager(playbooks_dir=str(pb_dir))

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "覆盖" in call_args


# ============================================
# deduplicate_risks 无循环内导入
# ============================================


class TestDedupNoLoopImport:
    """deduplicate_risks 不应在循环内延迟导入"""

    def test_dedup_works_with_many_items(self, engine):
        """大量去重项应正常工作"""
        risks = []
        for i in range(50):
            risks.append(
                RiskItem(
                    id=f"R_{i:03d}",
                    rule_id="",
                    name=f"风险{i % 5}",
                    category="测试",
                    risk_level="medium",
                    description="",
                    clause_content_preview=f"条款内容{i % 5}" * 10,
                )
            )
        result = engine.deduplicate_risks(risks)
        assert len(result) < 50


# ============================================
# 截断日志（P1-5）
# ============================================


class TestTruncationLogging:
    """超长文档截断应记录日志"""

    @pytest.mark.asyncio
    async def test_truncation_logs_segments(self, engine):
        """分段截断应记录段数信息"""
        text = "A" * 15000
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value="[]")

        with patch("src.analysis.risk_engine.logger_manager") as mock_logger:
            await engine.analyze_with_llm(
                text=text,
                document_type="contract",
                llm_client=mock_llm,
                max_segments=2,
            )

        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("段" in call for call in info_calls)
