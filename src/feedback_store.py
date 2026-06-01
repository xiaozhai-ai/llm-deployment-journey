"""
人工修正反馈存储模块 (Feedback Store)
- 记录用户对审查结果的修正
- 检索历史上相似条款的用户修正
- 导出为 Few-shot 示例用于 LLM 提示词
- 支持向量库增量学习
"""

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import get_paths_config
from src.logger import logger_manager
from src.utils import text_similarity


class CorrectionAction:
    """用户修正操作类型"""

    AGREE = "agree"  # 同意判断
    FALSE_POSITIVE = "false_positive"  # 误报
    LEVEL_DOWN = "level_down"  # 等级太高
    LEVEL_UP = "level_up"  # 等级太低
    MISSED_RISK = "missed_risk"  # 漏报（新增风险）


@dataclass
class FeedbackRecord:
    """反馈记录"""

    record_id: str
    timestamp: str
    document_type: str
    playbook_id: str
    clause_id: int
    clause_text: str  # 完整条款文本
    clause_title: str = ""
    original_risk: dict = field(default_factory=dict)  # 原始风险判断
    user_action: str = ""  # CorrectionAction
    user_comment: str = ""
    corrected_level: str | None = None  # 修正后的风险等级
    corrected_risk_name: str | None = None  # 修正后的风险名称（用于漏报补充）
    legal_basis_cited: str | None = None  # 用户引用的法条
    source: str = "human_correction"  # 数据来源

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FeedbackRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class FeedbackStore:
    """
    反馈存储管理器

    存储位置：config/feedback/feedback_records.jsonl

    功能：
    1. 记录用户修正
    2. 按条款内容相似度检索历史修正
    3. 导出为 Few-shot 示例
    4. 增量更新向量库（可选）
    """

    def __init__(self, feedback_dir: str | None = None):
        if feedback_dir:
            self.feedback_dir = Path(feedback_dir)
        else:
            # 从配置模块获取路径
            paths_config = get_paths_config()
            self.feedback_dir = paths_config["config_dir"] / "feedback"

        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self.records_file = self.feedback_dir / "feedback_records.jsonl"
        self.records: list[FeedbackRecord] = []
        self._write_lock = threading.Lock()
        self._load_records()

    def _load_records(self):
        """加载已有反馈记录"""
        if self.records_file.exists():
            skipped = 0
            with open(self.records_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            self.records.append(FeedbackRecord.from_dict(data))
                        except (json.JSONDecodeError, TypeError):
                            skipped += 1
            if skipped:
                logger_manager.warning(f"反馈记录加载：跳过 {skipped} 条损坏数据")

    def _save_record(self, record: FeedbackRecord):
        """追加保存单条记录（线程安全）"""
        line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        with self._write_lock, open(self.records_file, "a", encoding="utf-8") as f:
            f.write(line)

    def record_correction(
        self,
        clause_id: int,
        clause_text: str,
        clause_title: str,
        document_type: str,
        playbook_id: str,
        original_risk: dict,
        user_action: str,
        user_comment: str = "",
        corrected_level: str | None = None,
        corrected_risk_name: str | None = None,
        legal_basis_cited: str | None = None,
    ) -> FeedbackRecord:
        """
        记录用户修正

        Args:
            clause_id: 条款 ID
            clause_text: 条款文本
            clause_title: 条款标题
            document_type: 文档类型
            playbook_id: 审查策略
            original_risk: 原始风险判断 {name, risk_level, rule_id, ...}
            user_action: 修正操作类型
            user_comment: 用户备注
            corrected_level: 修正后的风险等级
            corrected_risk_name: 修正后的风险名称
            legal_basis_cited: 用户引用的法条

        Returns:
            FeedbackRecord
        """
        record = FeedbackRecord(
            record_id=self._generate_id(),
            timestamp=datetime.now().isoformat(),
            document_type=document_type,
            playbook_id=playbook_id,
            clause_id=clause_id,
            clause_text=clause_text[:2000],  # 限制长度
            clause_title=clause_title,
            original_risk=original_risk,
            user_action=user_action,
            user_comment=user_comment,
            corrected_level=corrected_level,
            corrected_risk_name=corrected_risk_name,
            legal_basis_cited=legal_basis_cited,
        )

        self.records.append(record)
        self._save_record(record)

        return record

    def get_similar_corrections(
        self, clause_text: str, max_results: int = 3, min_similarity: float = 0.3
    ) -> list[FeedbackRecord]:
        """
        检索历史上相似条款的用户修正

        Args:
            clause_text: 当前条款文本
            max_results: 最大返回数
            min_similarity: 最低相似度阈值

        Returns:
            相似修正记录列表
        """
        scored_records = []

        for record in self.records:
            similarity = text_similarity(clause_text, record.clause_text)
            if similarity >= min_similarity:
                scored_records.append((similarity, record))

        # 按相似度排序
        scored_records.sort(key=lambda x: x[0], reverse=True)

        return [record for _, record in scored_records[:max_results]]

    def get_corrections_for_risk_type(self, risk_name: str, max_results: int = 5) -> list[FeedbackRecord]:
        """
        获取某类风险的历史修正

        Args:
            risk_name: 风险名称
            max_results: 最大返回数

        Returns:
            修正记录列表
        """
        results = []
        for record in self.records:
            orig_risk = record.original_risk
            if orig_risk.get("name", "") == risk_name or risk_name in orig_risk.get("name", ""):
                results.append(record)

        return results[-max_results:]  # 最近的

    def export_as_few_shot(self, clause_text: str, risk_name: str = "") -> str:
        """
        导出为 Few-shot 示例（用于 LLM 提示词）

        Args:
            clause_text: 当前条款文本
            risk_name: 当前风险名称（可选过滤）

        Returns:
            Few-shot 提示词文本
        """
        records = []

        # 优先找相似条款的修正
        if clause_text:
            records = self.get_similar_corrections(clause_text, max_results=3)

        # 如果没找到，找同类风险的修正
        if not records and risk_name:
            records = self.get_corrections_for_risk_type(risk_name, max_results=3)

        if not records:
            return ""

        lines = ["\n## 历史人工修正参考（仅供参考，不代表最终判断）\n"]

        for i, record in enumerate(records, 1):
            orig = record.original_risk
            action_labels = {
                "agree": "✅ 用户同意该判断",
                "false_positive": "❌ 用户标记为误报",
                "level_down": "⬇️ 用户降低风险等级",
                "level_up": "⬆️ 用户提高风险等级",
                "missed_risk": "➕ 用户补充了新风险",
            }

            lines.append(f"### 示例 {i}")
            preview = record.clause_text[:100]
            if len(record.clause_text) > 100:
                preview += "…"
            lines.append(f"- 条款预览: {preview}")
            lines.append(f"- 原始判断: {orig.get('name', '')} [{orig.get('risk_level', '')}]")
            lines.append(f"- 用户操作: {action_labels.get(record.user_action, record.user_action)}")

            if record.user_comment:
                lines.append(f"- 用户说明: {record.user_comment}")

            if record.corrected_level:
                lines.append(f"- 修正后等级: {record.corrected_level}")

            if record.corrected_risk_name:
                lines.append(f"- 补充风险: {record.corrected_risk_name}")

            lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """获取反馈统计"""
        stats = {"total_records": len(self.records), "by_action": {}, "by_risk_type": {}, "false_positive_rate": 0.0}

        false_positives = 0
        for record in self.records:
            action = record.user_action
            stats["by_action"][action] = stats["by_action"].get(action, 0) + 1

            if action == CorrectionAction.FALSE_POSITIVE:
                false_positives += 1

            risk_name = record.original_risk.get("name", "unknown")
            stats["by_risk_type"][risk_name] = stats["by_risk_type"].get(risk_name, 0) + 1

        if len(self.records) > 0:
            stats["false_positive_rate"] = false_positives / len(self.records)

        return stats

    @staticmethod
    def _generate_id() -> str:
        return f"fb_{int(time.time() * 1000)}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}"


# 全局单例，线程安全
_feedback_store = None
_feedback_lock = threading.Lock()


def get_feedback_store() -> FeedbackStore:
    """获取全局反馈存储单例"""
    global _feedback_store
    if _feedback_store is None:
        with _feedback_lock:
            if _feedback_store is None:
                _feedback_store = FeedbackStore()
    return _feedback_store
