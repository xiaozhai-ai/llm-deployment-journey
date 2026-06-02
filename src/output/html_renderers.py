"""
HTML 渲染器

将审查结果、思考过程、溯源对照等数据转换为前端展示用的 HTML 片段。
"""

import html as _html

from src.infra.session_store import review_store


def _esc(text: str) -> str:
    """HTML 转义，防止 XSS"""
    return _html.escape(str(text), quote=True)


# ============================================
# 思考过程 & 工具调用
# ============================================

THINKING_CSS = """
.thinking-panel { font-family: "Microsoft YaHei", sans-serif; padding: 15px; background: #f0f7ff; border-radius: 8px; border-left: 4px solid #0d6efd; }
.thinking-step { margin: 6px 0; padding: 4px 0; font-size: 0.92em; }
.thinking-step .icon { margin-right: 6px; }
.thinking-header { font-weight: bold; font-size: 1.05em; margin-bottom: 10px; color: #0d6efd; }
.thinking-step.reflection { background: #fff3cd; padding: 4px 8px; border-radius: 4px; margin: 4px 0; }
"""

TOOL_CALL_CSS = """
.tool-call-log { font-family: "Microsoft YaHei", sans-serif; font-size: 0.9em; }
.tool-call-step { margin: 8px 0; padding: 8px 12px; border-radius: 6px; border-left: 3px solid #0d6efd; background: #f8f9fa; }
.tool-call-step .tool-name { font-weight: bold; color: #0d6efd; }
.tool-call-step .result { color: #6c757d; }
"""


def format_thinking_process(steps: list) -> str:
    """格式化 AI 思考过程展示"""
    if not steps:
        return '<div class="thinking-panel">✅ 审查完成（规则分析模式，未启用 AI 深度分析）</div>'

    html = [
        '<div class="thinking-panel">',
        "<style>",
        THINKING_CSS,
        "</style>",
        '<div class="thinking-header">🧠 AI 实时思考过程</div>',
    ]

    for step in steps:
        icon, css_class = _classify_thinking_step(step)
        display_text = _esc(step[:120] + "..." if len(step) > 120 else step)
        html.append(f'<div class="thinking-step {css_class}"><span class="icon">{icon}</span> {display_text}</div>')

    html.append('<div class="thinking-step"><span class="icon">✅</span> 审查完成</div>')
    html.append("</div>")
    return "\n".join(html)


def _classify_thinking_step(step: str):
    """根据内容判断思考步骤的图标和 CSS 类"""
    if "调用" in step:
        return "📡", ""
    elif "返回" in step:
        return "✅", ""
    elif "反思" in step:
        return "🔍", "reflection"
    elif "中断" in step or "停止" in step:
        return "🛑", ""
    return "🤔", ""


def format_tool_call_log(log_entries: list) -> str:
    """格式化工具调用过程展示"""
    if not log_entries:
        return ""

    html = ['<div class="tool-call-log">', "<style>", TOOL_CALL_CSS, "</style>", "<h4>🔧 AI 工具调用过程</h4>"]

    for entry in log_entries:
        html.append(
            f'<div class="tool-call-step">'
            f'<span class="tool-name">📡 {_esc(entry.get("tool", ""))}</span> '
            f"→ {_esc(entry.get('status', ''))}"
            f'<br><span class="result">{_esc(entry.get("detail", "")[:150])}</span>'
            f"</div>"
        )

    html.append("</div>")
    return "\n".join(html)


# ============================================
# 溯源对照视图
# ============================================

CLAUSES_CSS = """
.clauses-container { font-family: "Microsoft YaHei", sans-serif; }
.clause { margin: 10px 0; padding: 10px; border-radius: 6px; border: 1px solid #dee2e6; }
.clause.risk-critical { border-left: 4px solid #6f42c1; background: #f8f0ff; }
.clause.risk-high { border-left: 4px solid #dc3545; background: #fff5f5; }
.clause.risk-medium { border-left: 4px solid #ffc107; background: #fffbf0; }
.clause.risk-low { border-left: 4px solid #28a745; background: #f0fff4; }
.clause-title { font-weight: bold; margin-bottom: 5px; }
.clause-risk-tag { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; margin-left: 8px; }
.clause-risk-tag.critical { background: #6f42c1; color: white; }
.clause-risk-tag.high { background: #dc3545; color: white; }
.clause-risk-tag.medium { background: #ffc107; color: #333; }
.clause-risk-tag.low { background: #28a745; color: white; }
"""

RISKS_CSS = """
.risks-list { font-family: "Microsoft YaHei", sans-serif; padding: 10px; }
.risk-item { margin: 10px 0; padding: 10px; border-radius: 6px; border: 1px solid #dee2e6; cursor: pointer; }
.risk-item:hover { background: #f8f9fa; }
.risk-meta { font-size: 0.85em; color: #6c757d; margin-top: 5px; }
"""

LEVEL_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def build_trace_view() -> tuple:
    """构建溯源对照视图，返回 (clauses_html, risks_html)"""
    session_id = review_store.latest_session_id
    if not session_id:
        return "请先进行文件审查", "暂无风险"

    clauses = review_store.get_clauses(session_id)
    risks = review_store.get_risks(session_id)

    if not clauses and not risks:
        # 已有会话但无数据 → 审查已完成，只是没有发现风险
        return "✅ 审查完成，未发现可溯源的条款或风险", "✅ 未检测到风险"

    risk_by_clause = _index_risks_by_clause(risks)
    clauses_html = _render_clauses_html(clauses, risk_by_clause)
    risks_html = _render_risks_html(risks)

    return clauses_html, risks_html


def _index_risks_by_clause(risks: list) -> dict:
    """按 clause_id 建立风险索引"""
    index = {}
    for risk in risks:
        cid = risk.get("clause_id", 0)
        if cid not in index:
            index[cid] = []
        index[cid].append(risk)
    return index


def _render_clauses_html(clauses: list, risk_by_clause: dict) -> str:
    """渲染条款列表 HTML（带风险高亮）"""
    parts = ['<div class="clauses-container">', f"<style>{CLAUSES_CSS}</style>"]

    for clause in clauses:
        cid = clause.get("id", 0)
        title = _esc(clause.get("title", f"第{cid}条"))
        content = _esc(clause.get("content", "")[:500])

        clause_risks = risk_by_clause.get(cid, [])
        max_level = _max_risk_level(clause_risks)
        css_class = f"clause risk-{max_level}" if max_level else "clause"

        parts.append(f'<div class="{css_class}" id="clause-{cid}">')
        parts.append(f'<span class="clause-title">{title}</span>')

        for r in clause_risks:
            tag_class = r.get("risk_level", "low")
            parts.append(f'<span class="clause-risk-tag {tag_class}">{_esc(r.get("name", ""))}</span>')

        parts.append(f'<pre style="white-space:pre-wrap;margin:5px 0;font-size:0.9em;">{content}...</pre>')
        parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_risks_html(risks: list) -> str:
    """渲染风险列表 HTML（可点击定位）"""
    parts = ['<div class="risks-list">', f"<style>{RISKS_CSS}</style>"]

    if not risks:
        parts.append("<p>✅ 未检测到风险</p>")
    else:
        parts.append(f"<h4>共 {len(risks)} 个风险点</h4>")
        level_icons = {"critical": "🟣", "high": "🔴", "medium": "🟡", "low": "🟢"}

        for i, risk in enumerate(risks, 1):
            icon = level_icons.get(risk.get("risk_level", ""), "⚪")
            clause_id = risk.get("clause_id", 0)
            clause_title = risk.get("clause_title", "")
            cited = risk.get("cited_provisions", [])

            parts.append(
                f"<div class=\"risk-item\" onclick=\"document.getElementById('clause-{clause_id}')?.scrollIntoView({{behavior:'smooth'}})\">"
                f"<strong>{icon} 风险{i}: {_esc(risk.get('name', ''))}</strong><br>"
                f"<span>{_esc(risk.get('description', '')[:150])}...</span>"
            )

            if clause_title:
                parts.append(f'<div class="risk-meta">📍 条款: {_esc(clause_title)}（ID: {clause_id}）</div>')
            if cited:
                parts.append(f'<div class="risk-meta">📚 法条: {_esc("、".join(cited[:2]))}</div>')

            parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _max_risk_level(risks: list) -> str:
    """取一组风险中的最高等级"""
    max_level = ""
    for r in risks:
        rl = r.get("risk_level", "low")
        if LEVEL_ORDER.get(rl, 0) > LEVEL_ORDER.get(max_level, 0):
            max_level = rl
    return max_level
