"""
PlaybookManager 单元测试

覆盖：
- 内置策略加载
- YAML 策略加载
- StrictnessLevel 无效值降级
- 风险等级调整
- 策略列表
- 策略不存在抛 KeyError
"""

import pytest

from src.playbook_manager import PlaybookManager, StrictnessLevel


@pytest.fixture
def manager(tmp_path):
    # 创建一个有效的 YAML 策略文件
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    (pb_dir / "custom.yaml").write_text(
        "id: custom_test\n"
        "name: 自定义测试\n"
        "description: 测试用\n"
        "role: neutral\n"
        "strictness: high\n"
        "focus_areas: [测试领域]\n",
        encoding="utf-8",
    )
    # 清除内置策略（只测试自定义加载）
    return PlaybookManager(playbooks_dir=str(pb_dir))


class TestBuiltinPlaybooks:
    def test_neutral_exists(self, manager):
        pb = manager.get_playbook("neutral")
        assert pb.name == "中立审查"
        assert pb.strictness == StrictnessLevel.MEDIUM

    def test_party_a_exists(self, manager):
        pb = manager.get_playbook("party_a")
        assert pb.role == "party_a"
        assert "违约责任" in pb.focus_areas

    def test_party_b_exists(self, manager):
        pb = manager.get_playbook("party_b")
        assert pb.role == "party_b"

    def test_privacy_exists(self, manager):
        pb = manager.get_playbook("privacy_compliance")
        assert pb.strictness == StrictnessLevel.STRICT
        assert len(pb.required_clauses) > 0

    def test_labor_exists(self, manager):
        pb = manager.get_playbook("labor_contract")
        assert "劳动报酬" in pb.focus_areas


class TestCustomPlaybooks:
    def test_custom_loaded(self, manager):
        pb = manager.get_playbook("custom_test")
        assert pb.name == "自定义测试"
        assert pb.strictness == StrictnessLevel.HIGH

    def test_custom_focus_areas(self, manager):
        pb = manager.get_playbook("custom_test")
        assert "测试领域" in pb.focus_areas


class TestStrictnessFallback:
    def test_invalid_strictness_falls_back(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "bad.yaml").write_text(
            "id: bad\nname: 坏的\nstrictness: super_ultra\n",
            encoding="utf-8",
        )
        manager = PlaybookManager(playbooks_dir=str(pb_dir))
        pb = manager.get_playbook("bad")
        assert pb.strictness == StrictnessLevel.MEDIUM


class TestRiskAdjustment:
    def test_builtin_adjustment(self, manager):
        pb = manager.get_playbook("party_a")
        adjusted = pb.adjust_risk_level("IMBALANCE_001", "high")
        assert adjusted == "critical"

    def test_no_adjustment_keeps_original(self, manager):
        pb = manager.get_playbook("neutral")
        adjusted = pb.adjust_risk_level("UNKNOWN_RULE", "medium")
        assert adjusted == "medium"


class TestPlaybookMethods:
    def test_should_check_rule(self, manager):
        pb = manager.get_playbook("neutral")
        assert pb.should_check_rule("ANY_RULE") is True

    def test_excluded_rule(self, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "excl.yaml").write_text(
            "id: excl\nname: 排除\nstrictness: low\nexcluded_rules: [RULE_001]\n",
            encoding="utf-8",
        )
        manager = PlaybookManager(playbooks_dir=str(pb_dir))
        pb = manager.get_playbook("excl")
        assert pb.should_check_rule("RULE_001") is False
        assert pb.should_check_rule("RULE_002") is True

    def test_is_focus_area(self, manager):
        pb = manager.get_playbook("party_a")
        assert pb.is_focus_area("违约责任") is True
        assert pb.is_focus_area("不存在的领域") is False


class TestListPlaybooks:
    def test_list_returns_all(self, manager):
        items = manager.list_playbooks()
        ids = [p["id"] for p in items]
        assert "neutral" in ids
        assert "custom_test" in ids

    def test_choices_format(self, manager):
        choices = manager.get_playbook_choices()
        assert all(isinstance(c, tuple) and len(c) == 2 for c in choices)


class TestGetPlaybookNotFound:
    def test_raises_key_error(self, manager):
        with pytest.raises(KeyError, match="策略不存在"):
            manager.get_playbook("nonexistent_playbook")
