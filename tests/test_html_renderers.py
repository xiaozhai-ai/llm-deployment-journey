"""
HTML 渲染器单元测试

覆盖：
- 思考过程格式化
- 工具调用日志格式化
- 溯源对照视图（条款 + 风险）
- critical 等级支持
- XSS 防护
"""

import pytest
from unittest.mock import patch, MagicMock

from src.html_renderers import (
    format_thinking_process,
    format_tool_call_log,
    build_trace_view,
    _esc,
    _max_risk_level,
    _index_risks_by_clause,
    LEVEL_ORDER,
)


# ============================================
# XSS 转义
# ============================================

class TestEscaping:

    def test_esc_html_tags(self):
        assert _esc('<script>alert(1)</script>') == '&lt;script&gt;alert(1)&lt;/script&gt;'

    def test_esc_quotes(self):
        assert _esc('"onclick"') == '&quot;onclick&quot;'

    def test_esc_ampersand(self):
        assert _esc('A & B') == 'A &amp; B'

    def test_esc_normal_text(self):
        assert _esc('正常文本') == '正常文本'


# ============================================
# 思考过程
# ============================================

class TestThinkingProcess:

    def test_empty_steps(self):
        result = format_thinking_process([])
        assert "审查完成" in result
        assert "thinking-panel" in result

    def test_single_step(self):
        result = format_thinking_process(["正在分析文档结构"])
        assert "正在分析文档结构" in result
        assert "thinking-step" in result

    def test_multiple_steps(self):
        steps = ["调用法条搜索工具", "返回搜索结果", "反思分析结论"]
        result = format_thinking_process(steps)
        assert "📡" in result  # 调用图标
        assert "✅" in result  # 返回图标
        assert "🔍" in result  # 反思图标

    def test_long_step_truncated(self):
        long_step = "A" * 200
        result = format_thinking_process([long_step])
        assert "..." in result
        # 原始 200 字不应完整出现
        assert long_step not in result

    def test_xss_in_steps(self):
        result = format_thinking_process(["<img onerror=alert(1)>"])
        assert "<img" not in result
        assert "&lt;img" in result


# ============================================
# 工具调用日志
# ============================================

class TestToolCallLog:

    def test_empty_log(self):
        result = format_tool_call_log([])
        assert result == ""

    def test_single_entry(self):
        entries = [{"tool": "legal_search", "status": "成功", "detail": "找到3条法条"}]
        result = format_tool_call_log(entries)
        assert "legal_search" in result
        assert "找到3条法条" in result

    def test_xss_in_log(self):
        entries = [{"tool": "<script>", "status": "ok", "detail": "test"}]
        result = format_tool_call_log(entries)
        assert "<script>" not in result


# ============================================
# 溯源对照视图
# ============================================

class TestBuildTraceView:

    def test_no_session(self):
        with patch('src.html_renderers.review_store') as mock_store:
            mock_store.latest_session_id = None
            clauses_html, risks_html = build_trace_view()
            assert "请先进行文件审查" in clauses_html

    def test_empty_session(self):
        with patch('src.html_renderers.review_store') as mock_store:
            mock_store.latest_session_id = "s1"
            mock_store.get_clauses.return_value = []
            mock_store.get_risks.return_value = []
            clauses_html, risks_html = build_trace_view()
            assert "请先进行文件审查" in clauses_html

    def test_clauses_with_risks(self):
        with patch('src.html_renderers.review_store') as mock_store:
            mock_store.latest_session_id = "s1"
            mock_store.get_clauses.return_value = [
                {"id": 1, "title": "第一条", "content": "甲方义务"},
                {"id": 2, "title": "第二条", "content": "乙方义务"},
            ]
            mock_store.get_risks.return_value = [
                {"clause_id": 1, "name": "违约责任缺失", "risk_level": "high", "description": "未约定"},
                {"clause_id": 2, "name": "低风险项", "risk_level": "low", "description": "轻微"},
            ]
            clauses_html, risks_html = build_trace_view()

            assert "第一条" in clauses_html
            assert "risk-high" in clauses_html
            assert "违约责任缺失" in risks_html
            assert "共 2 个风险点" in risks_html

    def test_critical_risk_styling(self):
        with patch('src.html_renderers.review_store') as mock_store:
            mock_store.latest_session_id = "s1"
            mock_store.get_clauses.return_value = [
                {"id": 1, "title": "关键条款", "content": "重要内容"},
            ]
            mock_store.get_risks.return_value = [
                {"clause_id": 1, "name": "严重违规", "risk_level": "critical", "description": "严重"},
            ]
            clauses_html, risks_html = build_trace_view()

            assert "risk-critical" in clauses_html
            assert "🟣" in risks_html


# ============================================
# 风险等级工具函数
# ============================================

class TestRiskLevelUtils:

    def test_level_order_includes_critical(self):
        assert "critical" in LEVEL_ORDER
        assert LEVEL_ORDER["critical"] > LEVEL_ORDER["high"]

    def test_max_risk_level_critical_wins(self):
        risks = [
            {"risk_level": "low"},
            {"risk_level": "critical"},
            {"risk_level": "high"},
        ]
        assert _max_risk_level(risks) == "critical"

    def test_max_risk_level_empty(self):
        assert _max_risk_level([]) == ""

    def test_index_risks_by_clause(self):
        risks = [
            {"clause_id": 1, "name": "A"},
            {"clause_id": 1, "name": "B"},
            {"clause_id": 2, "name": "C"},
        ]
        index = _index_risks_by_clause(risks)
        assert len(index[1]) == 2
        assert len(index[2]) == 1
