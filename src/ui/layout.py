"""
Gradio 界面布局

所有 UI 组件定义和事件绑定，不包含业务逻辑。
业务逻辑由 src/handlers.py 提供，HTML 渲染由 src/html_renderers.py 提供。
"""

import gradio as gr

from src.html_renderers import build_trace_view
from src.handlers import (
    make_review_handler,
    make_chat_handler,
    make_search_handler,
    submit_feedback,
    show_feedback_stats,
)


CUSTOM_CSS = """
.disclaimer-box {
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 8px;
    padding: 15px;
    margin: 10px 0;
}
.progress-bar { font-weight: bold; }
.revision-view { border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; }
"""

HEADER = """
# ⚖️ 法务审查 Agent v2.0

> 增强版：多策略审查 · 多轮对话 · 修订追踪 · 异步处理
"""

DISCLAIMER = """
<div class="disclaimer-box">

⚠️ **免责声明**: 本工具生成的审查结果不构成正式法律意见，仅供参考，需专业律师复核。

</div>
"""

FOOTER = """
---
*法务审查 Agent v2.5 | 溯源高亮 · 人工修正反馈闭环 · 基于 AI 辅助分析 | 审查结果不构成法律意见*
"""


def create_ui(
    agent_loop,
    playbook_manager,
    legal_matcher,
    llm_client_factory,
    llm_api_key: str,
    max_file_size_mb: int = 10,
) -> gr.Blocks:
    """创建 Gradio 界面"""

    review_handler = make_review_handler(agent_loop, max_file_size_mb)
    chat_handler = make_chat_handler(llm_client_factory, llm_api_key)
    search_handler = make_search_handler(legal_matcher)

    with gr.Blocks(title="法务审查 Agent v2.0", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:

        gr.Markdown(HEADER)
        gr.Markdown(DISCLAIMER)

        with gr.Tabs():
            _build_review_tab(review_handler)
            _build_trace_tab()
            _build_feedback_tab()
            _build_chat_tab(chat_handler)
            _build_search_tab(search_handler)
            _build_freshness_tab()

        gr.Markdown(FOOTER)

    return demo


# ============================================
# Tab 构建函数
# ============================================

def _build_review_tab(review_handler):
    """📋 文件审查"""
    with gr.Tab("📋 文件审查"):
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📤 文件上传")

                file_input = gr.File(
                    label="上传法律文件",
                    file_types=[".pdf", ".docx", ".doc", ".txt"],
                    type="filepath"
                )

                gr.Markdown("### ⚙️ 审查配置")

                doc_type = gr.Dropdown(
                    choices=[
                        ("🔍 自动检测", "auto_detect"),
                        ("📄 合同", "contract"),
                        ("🤝 协议", "agreement"),
                        ("🔒 隐私政策", "privacy_policy"),
                    ],
                    value="auto_detect",
                    label="文件类型"
                )

                playbook_input = gr.Dropdown(
                    choices=[("🛡️ 甲方立场", "party_a"), ("⚔️ 乙方立场", "party_b"),
                             ("⚖️ 中立审查", "neutral"), ("🔒 隐私合规专项", "privacy_compliance"),
                             ("👷 劳动合同专项", "labor_contract")],
                    value="neutral",
                    label="审查策略"
                )

                use_llm = gr.Checkbox(
                    label="启用 AI 深度分析（需要 LLM_API_KEY）",
                    value=True
                )

                special_req = gr.Textbox(
                    label="特殊要求（可选）",
                    placeholder="例如：重点关注违约责任条款、检查是否符合《个人信息保护法》要求等",
                    lines=3
                )

                review_btn = gr.Button("🔍 开始审查", variant="primary", size="lg")

                gr.Markdown("""
###  使用说明

1. 上传 PDF / Word (.docx/.doc) / TXT 文件
2. 选择文件类型和审查策略
3. 点击「开始审查」
4. 查看报告和修订建议
                """)

            with gr.Column(scale=2):
                thinking_output = gr.HTML(
                    value='<div class="thinking-panel">⏳ 等待上传文件...</div>',
                    label="🧠 AI 实时思考过程"
                )
                _progress_bar = gr.Markdown("⏳ 准备就绪")
                warning_output = gr.Textbox(label="⚠️ 警告信息", lines=3, interactive=False, visible=True)
                report_output = gr.Markdown(label="📊 审查报告")
                tool_call_log_output = gr.HTML(label="🔧 AI 工具调用记录")

                gr.Markdown("### 📝 修订建议")
                revision_output = gr.HTML(label="修订对比")

                docx_download = gr.File(label="📥 下载修订版 DOCX", interactive=False, visible=False)

        review_btn.click(
            fn=review_handler,
            inputs=[file_input, doc_type, playbook_input, use_llm, special_req],
            outputs=[thinking_output, report_output, warning_output, tool_call_log_output, revision_output, docx_download]
        )


def _build_trace_tab():
    """🔗 溯源对照"""
    with gr.Tab("🔗 溯源对照"):
        gr.Markdown("### 🔗 原文-风险对照视图")
        gr.Markdown("左侧显示原文条款，高风险条款标红底色，中风险标黄，低风险标绿。点击风险项可高亮对应条款。")

        trace_clauses_html = gr.HTML(label="📄 原文条款（高亮风险点）")
        trace_risks_html = gr.HTML(label="⚠️ 风险列表（点击定位）")
        trace_btn = gr.Button("🔄 刷新对照视图", variant="primary")

        trace_btn.click(fn=build_trace_view, outputs=[trace_clauses_html, trace_risks_html])


def _build_feedback_tab():
    """🔄 人工修正"""
    with gr.Tab("🔄 人工修正"):
        gr.Markdown("### 🔄 人工修正与反馈")
        gr.Markdown("如果 Agent 判断有误，请在此处修正。您的反馈将帮助 Agent 下次不再犯同样的错误。")

        feedback_risk_dropdown = gr.Dropdown(
            label="选择要修正的风险项",
            choices=[],
            interactive=True
        )

        feedback_action = gr.Radio(
            choices=[
                ("✅ 同意判断", "agree"),
                ("❌ 误报（此条款无风险）", "false_positive"),
                ("⬇️ 等级太高", "level_down"),
                ("⬆️ 等级太低", "level_up"),
                ("➕ 漏报（补充新风险）", "missed_risk")
            ],
            label="您的判断",
            value="agree"
        )

        feedback_comment = gr.Textbox(
            label="修正说明（可选）",
            placeholder="例如：这是双方对等的违约责任，不存在不对等",
            lines=3
        )

        feedback_corrected_level = gr.Dropdown(
            label="修正后的风险等级（可选）",
            choices=["critical", "high", "medium", "low"],
            value="medium"
        )

        feedback_submit_btn = gr.Button("📤 提交修正", variant="primary")
        feedback_output = gr.Markdown(label="反馈结果")

        feedback_stats_btn = gr.Button("📊 查看反馈统计")
        feedback_stats_output = gr.Markdown(label="统计信息")

        feedback_submit_btn.click(
            fn=submit_feedback,
            inputs=[feedback_risk_dropdown, feedback_action, feedback_comment, feedback_corrected_level],
            outputs=[feedback_output]
        )

        feedback_stats_btn.click(fn=show_feedback_stats, outputs=[feedback_stats_output])


def _build_chat_tab(chat_handler):
    """💬 对话助手（流式输出）"""
    with gr.Tab("💬 对话助手"):
        gr.Markdown("### 💬 与法务助手对话")

        chatbot = gr.Chatbot(label="对话历史", height=400, type="messages")

        with gr.Row():
            chat_input = gr.Textbox(
                label="输入消息",
                placeholder="例如：我该如何选择审查策略？",
                scale=4
            )
            chat_send = gr.Button("发送", scale=1, variant="primary")

        chat_clear = gr.Button("🗑️ 清空对话")

        def _chat_and_clear(message, history):
            """发送后清空输入框"""
            for updated_history in chat_handler(message, history):
                yield updated_history, ""

        chat_send.click(
            fn=_chat_and_clear,
            inputs=[chat_input, chatbot],
            outputs=[chatbot, chat_input]
        )
        chat_input.submit(
            fn=_chat_and_clear,
            inputs=[chat_input, chatbot],
            outputs=[chatbot, chat_input]
        )
        chat_clear.click(lambda: ("", []), outputs=[chat_input, chatbot])


def _build_search_tab(search_handler):
    """📚 法规查询"""
    with gr.Tab("📚 法规查询"):
        gr.Markdown("### 📚 法律法规知识库查询")

        search_input = gr.Textbox(
            label="搜索关键词",
            placeholder="例如：违约责任、个人信息、格式条款"
        )
        search_btn = gr.Button("🔍 搜索", variant="primary")
        search_results = gr.Markdown(label="搜索结果")

        search_btn.click(fn=search_handler, inputs=[search_input], outputs=[search_results])


def _build_freshness_tab():
    """📅 知识库状态"""
    with gr.Tab("📅 知识库状态"):
        gr.Markdown("### 📅 知识库时效性报告")

        freshness_output = gr.Markdown(label="新鲜度报告")
        freshness_btn = gr.Button("🔄 检查知识库状态", variant="primary")

        def check_freshness() -> str:
            from src.knowledge_freshness import get_freshness_checker
            checker = get_freshness_checker()
            report = checker.check_all()
            return checker.format_report_for_display(report)

        freshness_btn.click(fn=check_freshness, outputs=[freshness_output])
