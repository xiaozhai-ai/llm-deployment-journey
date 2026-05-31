"""
知识库新鲜度检查器
- 检测法条/案例是否过期、废止、修订
- 生成时效性警告
- 提供知识库状态报告
"""

import os
import yaml
from datetime import datetime, date
from typing import List, Optional
from dataclasses import dataclass, field

from src.config import get_paths_config
from src.logger import logger_manager


class LegalStatus:
    """法条状态常量"""
    ACTIVE = "active"           # 现行有效
    AMENDED = "amended"         # 已修订（有新版本）
    REPEALED = "repealed"       # 已废止
    DRAFT = "draft"             # 草案/征求意见稿
    UNKNOWN = "unknown"         # 状态不明


@dataclass
class FreshnessWarning:
    """新鲜度警告"""
    item_type: str  # provision / case
    item_name: str  # 法条名称或案例标题
    status: str
    message: str
    severity: str  # critical / warning / info
    last_verified: Optional[str] = None
    days_since_verified: Optional[int] = None


@dataclass
class KnowledgeReport:
    """知识库状态报告"""
    generated_at: str
    total_provisions: int
    total_cases: int
    active_count: int
    amended_count: int
    repealed_count: int
    outdated_count: int  # 超过验证阈值的
    warnings: List[FreshnessWarning] = field(default_factory=list)
    overall_status: str = "healthy"  # healthy / needs_review / critical


class KnowledgeFreshnessChecker:
    """
    知识库新鲜度检查器

    职责：
    1. 检查法条/案例的状态标记
    2. 检测超过验证期限的条目
    3. 生成时效性警告
    4. 提供知识库整体状态报告
    """

    # 验证期限（天）
    VERIFICATION_THRESHOLD_DAYS = 180  # 6个月未验证标记为需核实
    CRITICAL_THRESHOLD_DAYS = 365      # 1年未验证标记为高风险

    STATUS_LABELS = {
        LegalStatus.ACTIVE: "现行有效",
        LegalStatus.AMENDED: "已修订",
        LegalStatus.REPEALED: "已废止",
        LegalStatus.DRAFT: "草案",
        LegalStatus.UNKNOWN: "状态不明"
    }

    def __init__(
        self,
        kb_path: Optional[str] = None,
        case_path: Optional[str] = None
    ):
        # 类级别缓存：同参数不重复加载
        cache_key = (kb_path, case_path)
        if hasattr(KnowledgeFreshnessChecker, '_cache') and KnowledgeFreshnessChecker._cache_key == cache_key:
            self.provisions = KnowledgeFreshnessChecker._cached_provisions
            self.cases = KnowledgeFreshnessChecker._cached_cases
            return

        self.provisions = []
        self.cases = []

        # 从配置模块获取路径
        paths_config = get_paths_config()

        if kb_path:
            self._load_provisions(kb_path)
        else:
            default_kb = paths_config["kb_path"]
            if default_kb.exists():
                self._load_provisions(str(default_kb))

        if case_path:
            self._load_cases(case_path)
        else:
            default_cases = paths_config["case_law_path"]
            if default_cases.exists():
                self._load_cases(str(default_cases))

        # 类级别缓存
        KnowledgeFreshnessChecker._cached_provisions = self.provisions
        KnowledgeFreshnessChecker._cached_cases = self.cases
        KnowledgeFreshnessChecker._cache_key = cache_key
        KnowledgeFreshnessChecker._cache = True

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """安全解析日期字符串，失败返回 None"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    def _load_provisions(self, path: str):
        """加载法条知识库"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as e:
            logger_manager.error(f"加载法条知识库失败 {path}: {e}")
            return

        for item in data.get('legal_provisions', []):
            self.provisions.append({
                'type': 'provision',
                'name': f"《{item['law']}》{item['article']}（{item['title']}）",
                'law': item['law'],
                'article': item['article'],
                'title': item['title'],
                'status': item.get('status', LegalStatus.ACTIVE),
                'effective_date': item.get('effective_date'),
                'repeal_date': item.get('repeal_date'),
                'repealed_by': item.get('repealed_by'),
                'last_verified': item.get('last_verified'),
                'keywords': item.get('keywords', [])
            })

    def _load_cases(self, path: str):
        """加载案例库"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as e:
            logger_manager.error(f"加载案例库失败 {path}: {e}")
            return

        for item in data.get('cases', []):
            self.cases.append({
                'type': 'case',
                'name': item.get('title', '未命名案例'),
                'case_number': item.get('case_number', ''),
                'status': item.get('status', LegalStatus.ACTIVE),
                'last_verified': item.get('last_verified'),
                'keywords': item.get('keywords', [])
            })

    def check_all(self) -> KnowledgeReport:
        """
        全面检查知识库新鲜度

        Returns:
            KnowledgeReport: 知识库状态报告
        """
        warnings = []
        active = 0
        amended = 0
        repealed = 0
        outdated = 0

        today = date.today()

        # 检查法条
        for p in self.provisions:
            status = p.get('status', LegalStatus.ACTIVE)
            last_verified = p.get('last_verified')

            if status == LegalStatus.ACTIVE:
                active += 1
            elif status == LegalStatus.AMENDED:
                amended += 1
            elif status == LegalStatus.REPEALED:
                repealed += 1

            # 检查验证时效
            if last_verified:
                verified_date = self._parse_date(last_verified)
                if verified_date:
                    days_since = (today - verified_date).days

                    if days_since > self.CRITICAL_THRESHOLD_DAYS:
                        outdated += 1
                        warnings.append(FreshnessWarning(
                            item_type='provision',
                            item_name=p['name'],
                            status=status,
                            message=f"该法条已 {days_since} 天未验证（超过 {self.CRITICAL_THRESHOLD_DAYS} 天），建议核实是否仍然有效",
                            severity='critical',
                            last_verified=last_verified,
                            days_since_verified=days_since
                        ))
                    elif days_since > self.VERIFICATION_THRESHOLD_DAYS:
                        warnings.append(FreshnessWarning(
                            item_type='provision',
                            item_name=p['name'],
                            status=status,
                            message=f"该法条已 {days_since} 天未验证，建议核实最新状态",
                            severity='warning',
                            last_verified=last_verified,
                            days_since_verified=days_since
                        ))

            # 已废止法条警告
            if status == LegalStatus.REPEALED:
                warnings.append(FreshnessWarning(
                    item_type='provision',
                    item_name=p['name'],
                    status=LegalStatus.REPEALED,
                    message="该法条已废止" + (f"（被{p.get('repealed_by', '新法')}取代）" if p.get('repealed_by') else ""),
                    severity='critical',
                    last_verified=last_verified
                ))

            # 已修订法条提示
            if status == LegalStatus.AMENDED:
                warnings.append(FreshnessWarning(
                    item_type='provision',
                    item_name=p['name'],
                    status=LegalStatus.AMENDED,
                    message="该法条已修订，请使用最新版本",
                    severity='warning',
                    last_verified=last_verified
                ))

        # 检查案例
        for c in self.cases:
            last_verified = c.get('last_verified')

            if last_verified:
                verified_date = self._parse_date(last_verified)
                if verified_date:
                    days_since = (today - verified_date).days

                    if days_since > self.CRITICAL_THRESHOLD_DAYS:
                        outdated += 1
                        warnings.append(FreshnessWarning(
                            item_type='case',
                            item_name=c['name'],
                            status=c.get('status', LegalStatus.ACTIVE),
                            message=f"该案例已 {days_since} 天未验证，裁判规则可能已变化",
                            severity='critical',
                            last_verified=last_verified,
                            days_since_verified=days_since
                        ))

        # 整体状态评估
        critical_count = sum(1 for w in warnings if w.severity == 'critical')
        total_items = len(self.provisions) + len(self.cases)
        if critical_count > 0:
            overall_status = "critical"
        elif total_items > 0 and outdated > total_items * 0.3:
            overall_status = "needs_review"
        else:
            overall_status = "healthy"

        return KnowledgeReport(
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_provisions=len(self.provisions),
            total_cases=len(self.cases),
            active_count=active,
            amended_count=amended,
            repealed_count=repealed,
            outdated_count=outdated,
            warnings=warnings,
            overall_status=overall_status
        )

    def check_items_referenced(self, cited_items: List[str]) -> List[FreshnessWarning]:
        """
        检查被引用的法条/案例的时效性

        Args:
            cited_items: 被引用的法条/案例标识列表
                格式: "《xxx法》第x条" 或 "案号"

        Returns:
            相关的新鲜度警告
        """
        relevant_warnings = []

        for item_id in cited_items:
            # 检查法条
            for p in self.provisions:
                p_full_name = f"《{p['law']}》{p['article']}"
                if p['law'] in item_id or p['article'] in item_id or p_full_name in item_id:
                    if p['status'] != LegalStatus.ACTIVE:
                        relevant_warnings.append(FreshnessWarning(
                            item_type='provision',
                            item_name=p['name'],
                            status=p['status'],
                            message=f"⚠️ 引用的法条状态为「{self.STATUS_LABELS.get(p['status'], p['status'])}」",
                            severity='critical'
                        ))
                    elif p.get('last_verified'):
                        parsed = self._parse_date(p['last_verified'])
                        if parsed:
                            days = (date.today() - parsed).days
                            if days > self.VERIFICATION_THRESHOLD_DAYS:
                                relevant_warnings.append(FreshnessWarning(
                                    item_type='provision',
                                    item_name=p['name'],
                                    status=p['status'],
                                    message=f"该法条已 {days} 天未验证，建议核实",
                                    severity='warning',
                                    last_verified=p['last_verified'],
                                    days_since_verified=days
                                ))

            # 检查案例
            for c in self.cases:
                if c.get('case_number') and c['case_number'] in item_id:
                    if c.get('last_verified'):
                        parsed = self._parse_date(c['last_verified'])
                        if parsed:
                            days = (date.today() - parsed).days
                            if days > self.VERIFICATION_THRESHOLD_DAYS:
                                relevant_warnings.append(FreshnessWarning(
                                    item_type='case',
                                    item_name=c['name'],
                                    status=c.get('status', LegalStatus.ACTIVE),
                                    message=f"该案例已 {days} 天未验证，裁判规则可能已变化",
                                    severity='warning',
                                    last_verified=c['last_verified'],
                                    days_since_verified=days
                                ))

        return relevant_warnings

    def format_report_for_display(self, report: KnowledgeReport) -> str:
        """格式化报告为显示文本"""
        lines = [
            "📊 知识库新鲜度报告",
            f"生成时间: {report.generated_at}",
            "",
            f"法条总数: {report.total_provisions}",
            f"  ✅ 现行有效: {report.active_count}",
            f"  🔄 已修订: {report.amended_count}",
            f"  ❌ 已废止: {report.repealed_count}",
            f"案例总数: {report.total_cases}",
            "",
            f"整体状态: {self._status_emoji(report.overall_status)} {self._status_label(report.overall_status)}",
        ]

        if report.warnings:
            lines.append(f"\n⚠️ 发现 {len(report.warnings)} 条时效性警告:\n")
            for w in report.warnings:
                severity_icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(w.severity, "⚪")
                lines.append(f"  {severity_icon} [{w.item_type}] {w.item_name}")
                lines.append(f"     {w.message}")
                if w.last_verified:
                    lines.append(f"     最后验证: {w.last_verified}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _status_emoji(status: str) -> str:
        return {"healthy": "✅", "needs_review": "⚠️", "critical": "🔴"}.get(status, "❓")

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "healthy": "健康",
            "needs_review": "需要复核",
            "critical": "存在过期数据"
        }.get(status, "未知")

    def get_freshness_disclaimer(self) -> str:
        """
        获取时效性免责声明（用于审查报告）

        Returns:
            声明文本
        """
        today = date.today().strftime('%Y年%m月%d日')
        return (
            f"📅 知识库时效性声明\n\n"
            f"本审查基于截至 {today} 的法律法规知识库。"
            f"法律法规可能随时修订或废止，建议通过"
            f"[国家法律法规数据库](https://flk.npc.gov.cn) 核实最新状态。\n\n"
            f"⚠️ 本工具的法规知识库为预置静态数据，不保证实时性。"
            f"对于重要法律事务，请务必核实引用的法条是否仍然有效。"
        )


# 全局单例
_freshness_checker = None

def get_freshness_checker() -> KnowledgeFreshnessChecker:
    """获取全局新鲜度检查器单例"""
    global _freshness_checker
    if _freshness_checker is None:
        _freshness_checker = KnowledgeFreshnessChecker()
    return _freshness_checker
