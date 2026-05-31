"""
审查指标收集器 (Metrics Collector)
- 追踪 LLM 调用次数、Token 消耗、耗时
- 估算费用
- 按任务/会话聚合
"""

import time
import threading
from typing import List, Optional
from dataclasses import dataclass, field


# 常见 LLM 模型定价（每百万 Token 价格，人民币）
# 基于通义千问 2025 年定价，可根据实际使用更新
MODEL_PRICING = {
    "qwen-turbo": {"input": 0.8, "output": 2.0},
    "qwen-plus": {"input": 4.0, "output": 12.0},
    "qwen-max": {"input": 20.0, "output": 60.0},
    "qwen-long": {"input": 0.5, "output": 2.0},
    # 兼容 OpenAI 模型
    "gpt-4o": {"input": 18.0, "output": 54.0},
    "gpt-4o-mini": {"input": 1.1, "output": 3.3},
    "gpt-3.5-turbo": {"input": 1.1, "output": 3.3},
    # 小米 MiMo 模型
    "mimo-v2.5-pro": {"input": 2.0, "output": 6.0},
    "mimo-v2-pro": {"input": 2.0, "output": 6.0},
}


@dataclass
class LLMCallRecord:
    """单次 LLM 调用记录"""
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0
    duration_ms: float = 0.0
    purpose: str = ""  # 调用目的（如"风险分析"、"自我反思"）
    timestamp: float = 0.0


@dataclass
class StageTiming:
    """阶段耗时"""
    stage_name: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0


@dataclass
class ReviewMetrics:
    """审查指标汇总"""
    task_id: str = ""
    filename: str = ""

    # 耗时
    total_duration_ms: float = 0.0
    stage_timings: List[StageTiming] = field(default_factory=list)

    # LLM 调用
    llm_call_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_cny: float = 0.0
    llm_calls: List[LLMCallRecord] = field(default_factory=list)

    # 工具调用
    tool_call_count: int = 0

    # 审查结果
    risk_count: int = 0
    high_risk_count: int = 0

    # 其他
    file_size_kb: float = 0.0
    clause_count: int = 0

    def add_stage(self, stage_name: str, duration_ms: float):
        """添加阶段耗时"""
        self.stage_timings.append(StageTiming(
            stage_name=stage_name,
            duration_ms=duration_ms
        ))

    def add_llm_call(self, model: str, prompt_tokens: int, completion_tokens: int,
                     duration_ms: float = 0.0, purpose: str = ""):
        """添加 LLM 调用记录"""
        total_tokens = prompt_tokens + completion_tokens

        # 计算费用
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)

        record = LLMCallRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_cny=cost,
            duration_ms=duration_ms,
            purpose=purpose,
            timestamp=time.time()
        )

        self.llm_calls.append(record)
        self.llm_call_count += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.estimated_cost_cny += cost

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """计算费用（人民币）"""
        pricing = MODEL_PRICING.get(model.lower(), MODEL_PRICING.get("qwen-plus"))
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def format_summary(self) -> str:
        """格式化指标摘要"""
        total_sec = self.total_duration_ms / 1000
        lines = [
            "📊 审查指标仪表盘",
            "",
            f"⏱️ **总耗时**: {total_sec:.1f} 秒",
            f"📄 **文件大小**: {self.file_size_kb:.1f} KB",
            f"📑 **条款数量**: {self.clause_count} 条",
            "",
            "🤖 **LLM 调用统计**",
            f"- 调用次数: {self.llm_call_count} 次",
            f"- 输入 Token: {self.total_prompt_tokens:,}",
            f"- 输出 Token: {self.total_completion_tokens:,}",
            f"- 总 Token: {self.total_tokens:,}",
            f"- 💰 估算费用: ¥{self.estimated_cost_cny:.4f}",
            "",
            f"🔧 **工具调用**: {self.tool_call_count} 次",
            "",
            "⚠️ **审查结果**",
            f"- 风险点: {self.risk_count} 个（高风险 {self.high_risk_count} 个）",
        ]

        if self.stage_timings:
            lines.append("")
            lines.append("⏱️ **各阶段耗时**")
            for stage in self.stage_timings:
                if stage.duration_ms > 0:
                    pct = (stage.duration_ms / self.total_duration_ms * 100) if self.total_duration_ms > 0 else 0
                    lines.append(f"- {stage.stage_name}: {stage.duration_ms/1000:.1f}s ({pct:.0f}%)")

        return "\n".join(lines)

    def format_html_dashboard(self) -> str:
        """格式化 HTML 仪表盘"""
        total_sec = self.total_duration_ms / 1000

        html = []
        html.append('<div class="metrics-dashboard">')
        html.append('<style>')
        html.append('.metrics-dashboard { font-family: "Microsoft YaHei", sans-serif; padding: 15px; }')
        html.append('.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 15px 0; }')
        html.append('.metric-card { background: #f8f9fa; border-radius: 8px; padding: 15px; text-align: center; border: 1px solid #dee2e6; }')
        html.append('.metric-card .value { font-size: 2em; font-weight: bold; color: #0d6efd; }')
        html.append('.metric-card .label { font-size: 0.9em; color: #6c757d; margin-top: 5px; }')
        html.append('.metric-card.cost .value { color: #dc3545; }')
        html.append('.metric-card.time .value { color: #198754; }')
        html.append('.metric-card.calls .value { color: #6f42c1; }')
        html.append('.stage-bar { margin: 5px 0; display: flex; align-items: center; }')
        html.append('.stage-bar .name { width: 120px; font-size: 0.9em; }')
        html.append('.stage-bar .bar { flex: 1; height: 20px; background: #e9ecef; border-radius: 4px; overflow: hidden; }')
        html.append('.stage-bar .bar-fill { height: 100%; background: #0d6efd; border-radius: 4px; transition: width 0.3s; }')
        html.append('.stage-bar .time { width: 80px; text-align: right; font-size: 0.85em; color: #6c757d; }')
        html.append('</style>')

        # 核心指标卡片
        html.append('<div class="metrics-grid">')

        html.append('<div class="metric-card time">')
        html.append(f'<div class="value">{total_sec:.1f}s</div>')
        html.append('<div class="label">⏱️ 总耗时</div>')
        html.append('</div>')

        html.append('<div class="metric-card calls">')
        html.append(f'<div class="value">{self.llm_call_count}</div>')
        html.append('<div class="label">🤖 LLM 调用次数</div>')
        html.append('</div>')

        html.append('<div class="metric-card">')
        html.append(f'<div class="value">{self.total_tokens:,}</div>')
        html.append('<div class="label">📝 总 Token 消耗</div>')
        html.append('</div>')

        html.append('<div class="metric-card cost">')
        html.append(f'<div class="value">¥{self.estimated_cost_cny:.4f}</div>')
        html.append('<div class="label">💰 估算费用</div>')
        html.append('</div>')

        html.append('<div class="metric-card">')
        html.append(f'<div class="value">{self.clause_count}</div>')
        html.append('<div class="label">📑 条款数量</div>')
        html.append('</div>')

        html.append('<div class="metric-card">')
        html.append(f'<div class="value">{self.risk_count}</div>')
        html.append('<div class="label">⚠️ 风险点</div>')
        html.append('</div>')

        html.append('</div>')  # end metrics-grid

        # Token 明细
        html.append('<div style="margin: 15px 0; font-size: 0.9em; color: #6c757d;">')
        html.append(f'📥 输入 Token: <b>{self.total_prompt_tokens:,}</b> | ')
        html.append(f'📤 输出 Token: <b>{self.total_completion_tokens:,}</b> | ')
        html.append(f'🔧 工具调用: <b>{self.tool_call_count}</b> 次')
        html.append('</div>')

        # 各阶段耗时瀑布图
        if self.stage_timings:
            html.append('<h4>⏱️ 各阶段耗时</h4>')
            max_duration = max((s.duration_ms for s in self.stage_timings), default=1)

            for stage in self.stage_timings:
                if stage.duration_ms <= 0:
                    continue
                pct = (stage.duration_ms / max_duration * 100)
                time_str = f"{stage.duration_ms/1000:.1f}s"
                html.append(
                    f'<div class="stage-bar">'
                    f'<span class="name">{stage.stage_name}</span>'
                    f'<div class="bar"><div class="bar-fill" style="width: {pct}%"></div></div>'
                    f'<span class="time">{time_str}</span>'
                    f'</div>'
                )

        # LLM 调用明细
        if self.llm_calls:
            html.append('<h4>🤖 LLM 调用明细</h4>')
            html.append('<table style="width:100%; border-collapse: collapse; font-size: 0.85em;">')
            html.append('<tr style="border-bottom: 1px solid #dee2e6;">')
            html.append('<th style="text-align: left; padding: 5px;">用途</th>')
            html.append('<th style="text-align: right; padding: 5px;">模型</th>')
            html.append('<th style="text-align: right; padding: 5px;">Token</th>')
            html.append('<th style="text-align: right; padding: 5px;">耗时</th>')
            html.append('<th style="text-align: right; padding: 5px;">费用</th>')
            html.append('</tr>')

            for call in self.llm_calls:
                html.append('<tr style="border-bottom: 1px solid #f0f0f0;">')
                html.append(f'<td style="padding: 5px;">{call.purpose or "通用"}</td>')
                html.append(f'<td style="text-align: right; padding: 5px;">{call.model}</td>')
                html.append(f'<td style="text-align: right; padding: 5px;">{call.total_tokens:,}</td>')
                html.append(f'<td style="text-align: right; padding: 5px;">{call.duration_ms/1000:.1f}s</td>')
                html.append(f'<td style="text-align: right; padding: 5px;">¥{call.cost_cny:.4f}</td>')
                html.append('</tr>')

            html.append('</table>')

        html.append('</div>')  # end metrics-dashboard

        return '\n'.join(html)


class MetricsCollector:
    """
    指标收集器（线程安全）

    用法：
    collector = MetricsCollector(task_id="xxx")
    with collector.stage("文件解析"):
        parser.parse(...)
    collector.record_llm_call(model="qwen-plus", prompt_tokens=1000, ...)
    metrics = collector.get_metrics()
    """

    def __init__(self, task_id: str = "", filename: str = ""):
        self.task_id = task_id
        self.filename = filename
        self.metrics = ReviewMetrics(task_id=task_id, filename=filename)
        self._lock = threading.Lock()
        self._current_stage = None
        self._start_time = time.time()

    class _StageContext:
        """阶段上下文（用于 with 语句）"""
        def __init__(self, collector: 'MetricsCollector', stage_name: str):
            self.collector = collector
            self.stage_name = stage_name
            self.start_time = 0.0

        def __enter__(self):
            self.start_time = time.time()
            return self

        def __exit__(self, *args):
            duration_ms = (time.time() - self.start_time) * 1000
            self.collector.metrics.add_stage(self.stage_name, duration_ms)

    def stage(self, stage_name: str) -> _StageContext:
        """
        创建阶段计时上下文

        用法：
        with collector.stage("文件解析"):
            do_something()
        """
        return self._StageContext(self, stage_name)

    def record_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float = 0.0,
        purpose: str = ""
    ):
        """记录 LLM 调用"""
        with self._lock:
            self.metrics.add_llm_call(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=duration_ms,
                purpose=purpose
            )

    def record_tool_call(self):
        """记录工具调用"""
        with self._lock:
            self.metrics.tool_call_count += 1

    def set_file_info(self, size_kb: float, clause_count: int):
        """设置文件信息"""
        with self._lock:
            self.metrics.file_size_kb = size_kb
            self.metrics.clause_count = clause_count

    def set_risk_stats(self, risk_count: int, high_risk_count: int):
        """设置风险统计"""
        with self._lock:
            self.metrics.risk_count = risk_count
            self.metrics.high_risk_count = high_risk_count

    def finalize(self):
        """最终化指标（计算总耗时）"""
        with self._lock:
            self.metrics.total_duration_ms = (time.time() - self._start_time) * 1000

    def get_metrics(self) -> ReviewMetrics:
        """获取指标汇总"""
        if self.metrics.total_duration_ms == 0:
            self.finalize()
        return self.metrics


# 全局收集器（当前任务），线程安全
_current_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()

def get_current_collector() -> Optional[MetricsCollector]:
    """获取当前任务的指标收集器"""
    with _collector_lock:
        return _current_collector

def set_current_collector(collector: Optional[MetricsCollector]):
    """设置当前任务的指标收集器"""
    global _current_collector
    with _collector_lock:
        _current_collector = collector
