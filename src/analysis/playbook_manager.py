"""
审查策略管理模块 (Playbook Manager)
- 管理不同立场的审查策略（甲方/乙方/中立/行业专项）
- 策略包含风险权重调整、关注条款、审查严格度等
- 支持自定义策略加载
"""

import os
from dataclasses import dataclass, field
from enum import Enum

import yaml

from src.core.config import get_paths_config
from src.infra.logger import logger_manager


class StrictnessLevel(Enum):
    """审查严格度"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    STRICT = "strict"


@dataclass
class RiskWeightAdjustment:
    """风险权重调整"""

    rule_id: str
    adjusted_level: str  # critical/high/medium/low
    reason: str = ""


@dataclass
class Playbook:
    """审查策略"""

    id: str
    name: str
    description: str
    role: str  # party_a / party_b / neutral / custom
    strictness: StrictnessLevel
    focus_areas: list[str] = field(default_factory=list)  # 重点关注领域
    risk_weight_adjustments: dict[str, RiskWeightAdjustment] = field(default_factory=dict)
    excluded_rules: list[str] = field(default_factory=list)  # 排除的规则
    required_clauses: list[str] = field(default_factory=list)  # 必须包含的条款
    custom_prompts: dict[str, str] = field(default_factory=dict)  # 自定义 LLM prompt 模板
    metadata: dict = field(default_factory=dict)

    def adjust_risk_level(self, rule_id: str, original_level: str) -> str:
        """
        根据策略调整风险等级

        Args:
            rule_id: 规则 ID
            original_level: 原始风险等级

        Returns:
            调整后的风险等级
        """
        if rule_id in self.risk_weight_adjustments:
            adjustment = self.risk_weight_adjustments[rule_id]
            return adjustment.adjusted_level
        return original_level

    def should_check_rule(self, rule_id: str) -> bool:
        """判断是否应该检查某条规则"""
        return rule_id not in self.excluded_rules

    def is_focus_area(self, category: str) -> bool:
        """判断某类别是否为关注领域"""
        return category in self.focus_areas


class PlaybookManager:
    """策略管理器"""

    # 风险等级优先级（用于调整）
    RISK_LEVEL_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    def __init__(self, playbooks_dir: str | None = None):
        self.playbooks: dict[str, Playbook] = {}
        self.default_playbook_id = "neutral"

        if playbooks_dir:
            self.playbooks_dir = playbooks_dir
        else:
            # 从配置模块获取路径
            paths_config = get_paths_config()
            self.playbooks_dir = str(paths_config["playbooks_dir"])

        self._load_builtin_playbooks()
        self._load_custom_playbooks()

    def _load_builtin_playbooks(self):
        """加载内置策略"""
        # 中立策略（默认）
        self.playbooks["neutral"] = Playbook(
            id="neutral",
            name="中立审查",
            description="标准中立审查，平衡双方利益",
            role="neutral",
            strictness=StrictnessLevel.MEDIUM,
            focus_areas=["条款完整性", "合规性", "格式条款"],
            metadata={"builtin": True},
        )

        # 甲方策略
        self.playbooks["party_a"] = Playbook(
            id="party_a",
            name="甲方立场",
            description="保护甲方利益，重点关注乙方违约责任和履约能力",
            role="party_a",
            strictness=StrictnessLevel.HIGH,
            focus_areas=["违约责任", "赔偿上限", "解除权", "知识产权归属", "保密条款"],
            risk_weight_adjustments={
                "IMBALANCE_001": RiskWeightAdjustment(
                    "IMBALANCE_001", "critical", "甲方视角：单方解除权不对等严重影响甲方利益"
                ),
                "IMBALANCE_002": RiskWeightAdjustment(
                    "IMBALANCE_002", "critical", "甲方视角：违约责任不对等可能导致甲方损失无法弥补"
                ),
                "COMPLIANCE_002": RiskWeightAdjustment(
                    "COMPLIANCE_002", "high", "甲方视角：过度免责条款可能使乙方逃避责任"
                ),
                "MISSING_CLAUSE_001": RiskWeightAdjustment(
                    "MISSING_CLAUSE_001", "critical", "甲方视角：违约责任条款缺失是重大风险"
                ),
            },
            custom_prompts={
                "risk_analysis": (
                    "你代表甲方审查此合同。请重点关注：\n"
                    "1. 乙方的违约责任是否明确且充分\n"
                    "2. 甲方是否拥有合理的解除权和监督权\n"
                    "3. 知识产权归属是否有利于甲方\n"
                    "4. 赔偿上限是否合理保护甲方利益\n"
                    "5. 保密条款是否充分保护甲方商业秘密"
                )
            },
            metadata={"builtin": True},
        )

        # 乙方策略
        self.playbooks["party_b"] = Playbook(
            id="party_b",
            name="乙方立场",
            description="保护乙方利益，重点关注责任限制和甲方义务",
            role="party_b",
            strictness=StrictnessLevel.HIGH,
            focus_areas=["责任限制", "付款条件", "甲方义务", "合理免责", "争议解决"],
            risk_weight_adjustments={
                "IMBALANCE_001": RiskWeightAdjustment(
                    "IMBALANCE_001", "critical", "乙方视角：甲方单方解除权可能导致乙方前期投入损失"
                ),
                "IMBALANCE_002": RiskWeightAdjustment(
                    "IMBALANCE_002", "critical", "乙方视角：过重的违约责任可能对乙方不公平"
                ),
                "FORMAT_001": RiskWeightAdjustment("FORMAT_001", "high", "乙方视角：格式条款未提示可能隐藏不利内容"),
                "FORMAT_002": RiskWeightAdjustment(
                    "FORMAT_002", "critical", "乙方视角：格式条款排除乙方权利必须重点关注"
                ),
                "IMBALANCE_003": RiskWeightAdjustment(
                    "IMBALANCE_003", "high", "乙方视角：不利管辖条款增加乙方维权成本"
                ),
            },
            custom_prompts={
                "risk_analysis": (
                    "你代表乙方审查此合同。请重点关注：\n"
                    "1. 乙方的违约责任是否过重或不合理\n"
                    "2. 甲方付款条件和义务是否明确\n"
                    "3. 是否存在对乙方不利的格式条款\n"
                    "4. 争议解决条款是否对乙方公平\n"
                    "5. 乙方是否拥有合理的免责和限制责任条款"
                )
            },
            metadata={"builtin": True},
        )

        # 隐私合规专项策略
        self.playbooks["privacy_compliance"] = Playbook(
            id="privacy_compliance",
            name="隐私合规专项",
            description="专注于个人信息保护和数据合规审查",
            role="neutral",
            strictness=StrictnessLevel.STRICT,
            focus_areas=["个人信息收集", "数据跨境", "用户权利", "安全措施", "合法性基础"],
            required_clauses=["信息收集范围", "信息使用目的", "信息共享规则", "信息安全措施", "用户权利", "联系方式"],
            custom_prompts={
                "risk_analysis": (
                    "请从《个人信息保护法》《数据安全法》角度审查此文件。\n"
                    "重点关注：\n"
                    "1. 个人信息收集是否符合最小必要原则\n"
                    "2. 是否明确告知用户信息处理目的和方式\n"
                    "3. 用户权利（查阅、复制、删除、更正）是否充分保障\n"
                    "4. 数据跨境传输是否满足法定条件\n"
                    "5. 是否建立数据安全管理制度"
                )
            },
            metadata={"builtin": True, "industry": "privacy"},
        )

        # 劳动合同专项策略
        self.playbooks["labor_contract"] = Playbook(
            id="labor_contract",
            name="劳动合同专项",
            description="专注于劳动合同合规审查",
            role="neutral",
            strictness=StrictnessLevel.HIGH,
            focus_areas=["劳动报酬", "工作时间", "社会保险", "解除条件", "竞业限制"],
            custom_prompts={
                "risk_analysis": (
                    "请从《劳动合同法》角度审查此劳动合同。\n"
                    "重点关注：\n"
                    "1. 劳动报酬是否明确且不低于最低工资标准\n"
                    "2. 工作时间和休息休假是否符合法定标准\n"
                    "3. 社会保险缴纳义务是否明确\n"
                    "4. 合同解除条件是否合法\n"
                    "5. 竞业限制条款是否合理（期限、补偿金）"
                )
            },
            metadata={"builtin": True, "industry": "labor"},
        )

    def _load_custom_playbooks(self):
        """从配置文件加载自定义策略"""
        if not os.path.exists(self.playbooks_dir):
            return

        for filename in os.listdir(self.playbooks_dir):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                filepath = os.path.join(self.playbooks_dir, filename)
                try:
                    playbook = self._load_playbook_from_yaml(filepath)
                    if playbook:
                        if playbook.id in self.playbooks:
                            logger_manager.warning(
                                f"自定义策略「{playbook.id}」（来自 {filename}）"
                                f"将覆盖已有策略「{self.playbooks[playbook.id].name}」"
                            )
                        self.playbooks[playbook.id] = playbook
                except Exception as e:
                    logger_manager.warning(f"加载策略文件失败 {filepath}: {e}")

    def _load_playbook_from_yaml(self, filepath: str) -> Playbook | None:
        """从 YAML 文件加载策略"""
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "id" not in data:
            return None

        # 解析严格度（无效值降级为 MEDIUM）
        try:
            strictness = StrictnessLevel(data.get("strictness", "medium"))
        except ValueError:
            logger_manager.warning(f"策略文件 {filepath} 的 strictness 值无效，降级为 medium")
            strictness = StrictnessLevel.MEDIUM

        # 解析风险权重调整
        risk_adjustments = {}
        for rule_id, adj_data in data.get("risk_weight_adjustments", {}).items():
            if isinstance(adj_data, str):
                risk_adjustments[rule_id] = RiskWeightAdjustment(rule_id=rule_id, adjusted_level=adj_data)
            elif isinstance(adj_data, dict):
                risk_adjustments[rule_id] = RiskWeightAdjustment(
                    rule_id=rule_id,
                    adjusted_level=adj_data.get("level", adj_data.get("adjusted_level", "medium")),
                    reason=adj_data.get("reason", ""),
                )

        return Playbook(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            role=data.get("role", "neutral"),
            strictness=strictness,
            focus_areas=data.get("focus_areas", []),
            risk_weight_adjustments=risk_adjustments,
            excluded_rules=data.get("excluded_rules", []),
            required_clauses=data.get("required_clauses", []),
            custom_prompts=data.get("custom_prompts", {}),
            metadata=data.get("metadata", {}),
        )

    def get_playbook(self, playbook_id: str) -> Playbook:
        """
        获取策略

        Args:
            playbook_id: 策略 ID

        Returns:
            Playbook 对象

        Raises:
            KeyError: 策略不存在
        """
        if playbook_id not in self.playbooks:
            raise KeyError(f"策略不存在: {playbook_id}")
        return self.playbooks[playbook_id]

    def list_playbooks(self) -> list[dict]:
        """
        列出所有可用策略

        Returns:
            策略信息列表
        """
        result = []
        for _pid, pb in self.playbooks.items():
            result.append(
                {
                    "id": pb.id,
                    "name": pb.name,
                    "description": pb.description,
                    "role": pb.role,
                    "strictness": pb.strictness.value,
                    "focus_areas": pb.focus_areas,
                    "is_builtin": pb.metadata.get("builtin", False),
                }
            )
        return result

    def get_playbook_choices(self) -> list[tuple]:
        """
        获取策略选择列表（用于 UI Dropdown）

        Returns:
            [(显示名称, 策略ID), ...]
        """
        return [(pb.name, pb.id) for pb in sorted(self.playbooks.values(), key=lambda x: x.id)]

    def create_playbook_from_config(self, config: dict) -> Playbook:
        """
        从配置字典创建策略

        Args:
            config: 策略配置字典

        Returns:
            Playbook 对象
        """
        playbook = Playbook(
            id=config["id"],
            name=config.get("name", config["id"]),
            description=config.get("description", ""),
            role=config.get("role", "neutral"),
            strictness=StrictnessLevel(config.get("strictness", "medium")),
            focus_areas=config.get("focus_areas", []),
            excluded_rules=config.get("excluded_rules", []),
            required_clauses=config.get("required_clauses", []),
            custom_prompts=config.get("custom_prompts", {}),
            metadata=config.get("metadata", {}),
        )

        # 解析风险权重调整
        for rule_id, adj_data in config.get("risk_weight_adjustments", {}).items():
            if isinstance(adj_data, str):
                playbook.risk_weight_adjustments[rule_id] = RiskWeightAdjustment(
                    rule_id=rule_id, adjusted_level=adj_data
                )
            elif isinstance(adj_data, dict):
                playbook.risk_weight_adjustments[rule_id] = RiskWeightAdjustment(
                    rule_id=rule_id,
                    adjusted_level=adj_data.get("level", adj_data.get("adjusted_level", "medium")),
                    reason=adj_data.get("reason", ""),
                )

        # 注册到管理器
        self.playbooks[playbook.id] = playbook
        return playbook
