# 法务审查 Agent

基于 AI 的法律文件自动化风险识别工具，支持合同/协议/隐私政策等多种法律文件。

## 技术栈

- Python 3.10+ / Gradio UI
- ChromaDB 向量检索
- LLM: 通义千问 (qwen-plus) 兼容接口
- 部署: Hugging Face Spaces / 本地

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动应用
python app.py

# 运行测试
pytest tests/

# 代码检查
ruff check src/
```

## 目录结构

```
├── app.py                 # 入口 (模块初始化 + Gradio 启动)
├── config/                # 配置文件
│   ├── legal_rules.yaml   # 风险规则
│   ├── legal_kb.yaml      # 法律法规知识库
│   ├── case_law.yaml      # 判例库
│   └── playbooks/         # 审查策略 (甲方/乙方/隐私/劳动合同)
├── src/
│   ├── agent_loop.py      # Agent 主循环
│   ├── tool_agent.py      # Tool-Calling Agent
│   ├── risk_engine.py     # 风险识别引擎
│   ├── legal_matcher.py   # 法条匹配
│   ├── vector_store.py    # ChromaDB 向量存储
│   ├── llm_client.py      # LLM API 客户端
│   ├── handlers.py        # 业务逻辑处理器
│   ├── tools/             # 工具集 (法规/判例检索, 歧义检测)
│   └── ui/                # Gradio 界面层
├── tests/                 # 测试
└── requirements.txt
```

## 核心功能

- 多策略审查: 甲方/乙方/中立/隐私合规/劳动合同
- 溯源高亮: 风险项 → 原文条款跳转
- 人工修正反馈闭环: 标记误报 → 注入 LLM Few-shot
- 向量语义 + 关键词 + 术语强制召回
- 修订追踪: HTML 对比 + DOCX Track Changes

## 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | API 密钥 (必需) |
| `LLM_API_BASE` | API URL (默认通义千问) |
| `LLM_MODEL` | 模型名 (默认 qwen-plus) |
