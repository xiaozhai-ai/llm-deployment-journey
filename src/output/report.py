"""
报告生成模块
生成结构化的法律审查报告
"""

from dataclasses import dataclass, field
from datetime import datetime

from src.analysis.knowledge_freshness import get_freshness_checker


@dataclass
class ReviewReport:
    """审查报告"""

    report_id: str
    document_name: str
    document_type: str
    review_time: str
    risk_summary: dict[str, int]
    risks: list[dict]
    security_warning: str | None
    disclaimer: str = ""
    suggestions: list[str] = field(default_factory=list)


class ReportGenerator:
    """报告生成器"""

    DISCLAIMER = (
        "⚠️ 免责声明：本工具生成的审查结果仅基于自动化分析，不构成正式法律意见。"
        "审查结果仅供参考，不能替代专业律师的法律意见。对于重要法律事务，"
        "建议咨询具有执业资格的律师进行复核。"
    )

    _LEVEL_CN = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}

    def __init__(self):
        pass

    def generate_report(
        self,
        document_name: str,
        document_type: str,
        risk_result,  # RiskAnalysisResult
        legal_matches: list,  # List of LegalMatch
        security_warning: str | None = None,
        sensitive_items: list | None = None,
    ) -> str:
        """
        生成完整的审查报告（Markdown 格式）

        Args:
            document_name: 文档名称
            document_type: 文档类型
            risk_result: 风险分析结果
            legal_matches: 法条匹配结果
            security_warning: 安全警告
            sensitive_items: 敏感信息列表

        Returns:
            Markdown 格式的报告
        """
        report_id = f"LR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        parts = []

        # 报告头部
        parts.append(self._generate_header(report_id, document_name, document_type, review_time))

        # 安全提示
        if security_warning:
            parts.append(self._generate_security_section(security_warning, sensitive_items))

        # 风险概览
        parts.append(self._generate_risk_summary(risk_result))

        # 详细风险列表
        parts.append(self._generate_risk_details(risk_result, legal_matches))

        # 建议汇总
        parts.append(self._generate_suggestions(risk_result))

        # 知识库新鲜度报告（仅在有警告时显示）
        freshness_section = self.generate_freshness_section()
        if freshness_section:
            parts.append(freshness_section)

        # 免责声明
        timeliness = get_freshness_checker().get_freshness_disclaimer()
        parts.append(self._generate_disclaimer(timeliness))

        return "\n\n".join(parts)

    def generate_report_dict(
        self,
        document_name: str,
        document_type: str,
        risk_result,
        legal_matches: list,
        security_warning: str | None = None,
        sensitive_items: list | None = None,
    ) -> dict:
        """
        生成结构化的报告字典（用于 API 返回）

        Returns:
            报告字典
        """
        risks_list = []
        for risk in risk_result.risks:
            risk_dict = {
                "id": risk.id,
                "name": risk.name,
                "category": risk.category,
                "risk_level": risk.risk_level,
                "risk_level_cn": {"critical": "严重", "high": "高", "medium": "中", "low": "低"}.get(
                    risk.risk_level, "中"
                ),
                "description": risk.description,
                "clause_position": risk.clause_position,
                "legal_basis": risk.legal_basis,
                "suggestion": risk.suggestion,
                "confidence": risk.confidence,
            }
            risks_list.append(risk_dict)

        return {
            "report_id": f"LR-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "document_name": document_name,
            "document_type": document_type,
            "review_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "risk_summary": {
                "critical": risk_result.critical_count,
                "high": risk_result.high_count,
                "medium": risk_result.medium_count,
                "low": risk_result.low_count,
                "total": len(risk_result.risks),
            },
            "risks": risks_list,
            "security_warning": security_warning,
            "disclaimer": self.DISCLAIMER,
            "timeliness_disclaimer": get_freshness_checker().get_freshness_disclaimer(),
        }

    def generate_freshness_section(self) -> str:
        """生成知识库新鲜度报告段落（插入到报告中）"""
        try:
            freshness = get_freshness_checker()
            report = freshness.check_all()
        except Exception:
            return ""

        if report.overall_status == "healthy" and not report.warnings:
            return ""

        lines = ["## 📅 知识库新鲜度报告"]
        lines.append(f"知识库整体状态: **{freshness._status_label(report.overall_status)}**")
        lines.append(f"法条总数: {report.total_provisions} | 现行有效: {report.active_count}")
        lines.append(f"案例总数: {report.total_cases}")

        if report.warnings:
            critical_warnings = [w for w in report.warnings if w.severity == "critical"]
            if critical_warnings:
                lines.append(f"\n🔴 发现 {len(critical_warnings)} 条严重时效性警告:\n")
                for w in critical_warnings[:5]:
                    lines.append(f"- **{w.item_name}**: {w.message}")

        lines.append("")
        return "\n".join(lines)

    def _generate_header(self, report_id: str, doc_name: str, doc_type: str, review_time: str) -> str:
        """生成报告头部"""
        type_names = {"contract": "合同", "agreement": "协议", "privacy_policy": "隐私政策", "unknown": "法律文件"}
        type_cn = type_names.get(doc_type, doc_type)

        return f"""# 📋 法务审查报告

| 项目 | 内容 |
|------|------|
| 报告编号 | {report_id} |
| 文件名称 | {doc_name} |
| 文件类型 | {type_cn} |
| 审查时间 | {review_time} |"""

    def _generate_security_section(self, warning: str, sensitive_items: list | None = None) -> str:
        """生成安全提示部分"""
        section = f"""## 🔒 安全提示

{warning}"""

        if sensitive_items:
            section += """

### 检测到的敏感信息

| 类型 | 原始值（已脱敏） |
|------|-----------------|"""
            for item in sensitive_items[:10]:  # 最多显示10条
                section += f"\n| {item.type} | {item.masked_value} |"
            section += "\n\n> 💡 建议在上传前对敏感信息进行脱敏处理"

        return section

    def _generate_risk_summary(self, risk_result) -> str:
        """生成风险概览"""
        total = len(risk_result.risks)

        summary = f"""## 📊 风险概览

| 风险等级 | 数量 |
|----------|------|
| 🟣 严重风险 | {risk_result.critical_count} |
| 🔴 高风险 | {risk_result.high_count} |
| 🟡 中风险 | {risk_result.medium_count} |
| 🟢 低风险 | {risk_result.low_count} |
| **合计** | **{total}** |"""

        if total == 0:
            summary += "\n\n✅ **未检测到明显风险**（仍需专业律师复核）"

        return summary

    def _generate_risk_details(self, risk_result, legal_matches) -> str:
        """生成详细风险列表"""
        if not risk_result.risks:
            return "## 📝 详细风险分析\n\n未发现明显风险点。"

        parts = ["## 📝 详细风险分析"]

        # 按风险等级排序
        level_order = {"critical": -2, "high": -1, "medium": 0, "low": 1}
        sorted_risks = sorted(risk_result.risks, key=lambda r: level_order.get(r.risk_level, 0))

        for i, risk in enumerate(sorted_risks, 1):
            level_icon = {"critical": "🟣", "high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk.risk_level, "⚪")
            level_cn = {"critical": "严重风险", "high": "高风险", "medium": "中风险", "low": "低风险"}.get(
                risk.risk_level, "未知"
            )

            risk_section = f"""
### {level_icon} 风险 {i}: {risk.name}

- **风险等级**: {level_cn}
- **风险类别**: {risk.category}
- **风险描述**: {risk.description}"""

            # 溯源信息（v2.5）
            if risk.clause_title:
                risk_section += f"\n- 📍 **条款位置**: {risk.clause_title}"
                if risk.clause_line_range:
                    risk_section += f"（{risk.clause_line_range}）"

            if risk.clause_content_preview:
                preview = risk.clause_content_preview[:100]
                suffix = "…" if len(risk.clause_content_preview) > 100 else ""
                risk_section += f"\n- **条款预览**: 「{preview}{suffix}」"

            if risk.legal_basis:
                risk_section += f"\n- 📖 **法律依据**: {risk.legal_basis}"

            # 引用法条列表（v2.5）
            if risk.cited_provisions:
                risk_section += f"\n- 📚 **相关法条**: {'、'.join(risk.cited_provisions)}"

            if risk.suggestion:
                risk_section += f"\n- **修改建议**: {risk.suggestion}"

            risk_section += f"\n- **置信度**: {risk.confidence:.0%}"

            parts.append(risk_section)

        return "\n".join(parts)

    def _generate_suggestions(self, risk_result) -> str:
        """生成建议汇总"""
        suggestions = []

        for risk in risk_result.risks:
            if risk.suggestion:
                level_cn = self._LEVEL_CN.get(risk.risk_level, risk.risk_level)
                suggestions.append(f"- [{level_cn}] {risk.name}: {risk.suggestion}")

        if not suggestions:
            return "## 💡 合规建议\n\n暂无额外建议。"

        return f"""## 💡 合规建议

{chr(10).join(suggestions)}

> 💡 以上建议仅供参考，具体修改方案需结合业务实际情况并由专业律师确认。"""

    def _generate_disclaimer(self, timeliness_disclaimer: str = "") -> str:
        """生成免责声明 + 时效性声明"""
        if not timeliness_disclaimer:
            timeliness_disclaimer = get_freshness_checker().get_freshness_disclaimer()

        return f"""---

## ⚖️ 免责声明

{self.DISCLAIMER}

---

{timeliness_disclaimer}

---
*本报告由 AI 辅助生成，审查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*"""
