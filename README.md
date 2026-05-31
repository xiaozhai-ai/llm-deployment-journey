# 法务审查 Agent v2.0

> ⚠️ **免责声明**: 本工具生成的审查结果不构成正式法律意见，仅供参考，需专业律师复核。

## 简介

基于 AI 的法律文件自动化风险识别与初步审查工具，支持合同、协议、隐私政策等多种法律文件类型。

**v2.5 新增功能**:
- 🔗 **溯源高亮**: 原文-风险对照视图，点击风险项自动跳转到对应条款，展示条款位置、引用法条
- 🔄 **人工修正反馈闭环**: 用户可标记误报/修正等级，反馈自动注入 LLM Few-shot 提示词，下次不再犯同样错误
- 📅 **时效性检测**: 法条/判例状态标注、过期预警、知识库新鲜度报告，防止"一本正经地胡说八道"
- 🔍 **多路精准召回**: 向量语义 + 关键词扩展 + 法律术语强制召回，解决"漏法条"问题（如"定金"≠"订金"）
- 🪞 **自我反思**: 结论输出前自动验证法条/判例引用准确性，修正幻觉引用
- 🤖 **Tool-Calling Agent**: AI 自主调用法规/判例检索工具，支撑审查结论
- 🎯 **多策略审查**: 甲方/乙方/中立/行业专项策略，不同立场审查标准自动调整
- 📝 **修订追踪**: LLM 生成修订后文本，支持 HTML 对比视图和 DOCX Track Changes 下载
- 💬 **多轮对话**: Agent 可基于上下文追问，引导用户补充必要信息
- 🔍 **向量检索**: ChromaDB 语义检索，法条匹配更精准
- ⏱️ **异步处理**: 后台任务队列 + 实时进度条
- 📊 **日志系统**: 操作审计 + LLM 推理链路记录

## 快速部署

### Hugging Face Spaces

1. 在 [Hugging Face](https://huggingface.co/) 创建新 **Space**，SDK 选择 **Gradio**
2. 将本项目文件上传到 Space 仓库
3. 在 **Settings → Secrets** 配置 API 密钥
4. Space 自动构建启动

### 本地运行

```bash
pip install -r requirements.txt
export LLM_API_KEY="your-api-key"
python app.py
```

## 配置

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_API_KEY` | 第三方 LLM API 密钥 | 必需 |
| `LLM_API_BASE` | API 基础 URL | 通义千问兼容接口 |
| `LLM_MODEL` | 模型名称 | `qwen-plus` |
| `MAX_FILE_SIZE_MB` | 最大文件大小 (MB) | 10 |

## 项目结构

```
legal-review-agent/
├── app.py                    # 应用入口（模块初始化 + 启动）
├── requirements.txt          # Python 依赖
├── README.md                 # 项目说明
├── DEPLOYMENT.md             # 部署指南
├── config/
│   ├── legal_rules.yaml      # 风险规则配置
│   ├── legal_kb.yaml         # 法律法规知识库（含 status / last_verified 字段）
│   ├── case_law.yaml         # 预置判例库（含 status / last_verified 字段）
│   └── playbooks/            # 审查策略配置
│       ├── party_a.yaml      # 甲方立场
│       ├── party_b.yaml      # 乙方立场
│       ├── privacy_compliance.yaml  # 隐私合规专项
│       └── labor_contract.yaml      # 劳动合同专项
├── src/
│   ├── __init__.py
│   ├── parser.py             # 文件解析模块
│   ├── security.py           # 安全合规模块
│   ├── risk_engine.py        # 风险识别引擎（v2.5 增加 clause_id 溯源关联）
│   ├── legal_matcher.py      # 法条匹配模块
│   ├── report.py             # 报告生成模块（v2.5 含溯源信息）
│   ├── llm_client.py         # LLM API 客户端（v2.1 支持 Tool Calling）
│   ├── logger.py             # 日志系统
│   ├── playbook_manager.py   # 审查策略管理
│   ├── vector_store.py       # ChromaDB 向量存储（v2.3 多路精准召回）
│   ├── redliner.py           # 修订生成器
│   ├── chat_memory.py        # 对话记忆管理
│   ├── agent_loop.py         # Agent 主循环（v2.5 增加溯源关联步骤）
│   ├── task_runner.py        # 异步任务执行器
│   ├── tool_agent.py         # Tool-Calling Agent（v2.5 注入历史修正）
│   ├── knowledge_freshness.py # 知识库新鲜度检查器（v2.4 新增）
│   ├── legal_terms.py        # 法律术语词典（v2.3 新增）
│   ├── feedback_store.py     # 人工修正反馈存储（v2.5 新增）
│   ├── session_store.py      # Session 级别审查结果存储（线程安全）
│   ├── html_renderers.py     # HTML 渲染器（思考过程/溯源对照/风险列表）
│   ├── handlers.py           # 业务逻辑处理器（审查/对话/反馈/搜索）
│   ├── exceptions.py         # 自定义异常类体系
│   ├── metrics.py            # 指标模块
│   ├── tools/                # 工具集（v2.1 新增）
│   │   ├── base.py           # 工具基类与注册表
│   │   ├── legal_search.py   # 法规检索工具
│   │   ├── case_search.py    # 判例检索工具
│   │   └── ambiguity_check.py # 歧义检测工具
│   └── ui/                   # Gradio 界面层
│       ├── __init__.py
│       └── layout.py         # 界面布局与事件绑定
```

## 功能特性

### 多策略审查
- **甲方立场**: 重点关注乙方违约责任、赔偿上限、解除权
- **乙方立场**: 重点关注责任限制、付款条件、格式条款
- **中立审查**: 平衡双方利益
- **隐私合规专项**: 《个人信息保护法》《数据安全法》合规审查
- **劳动合同专项**: 《劳动合同法》合规审查

### 风险识别
- 条款缺失检测
- 权利义务失衡检测
- 合规性冲突检测
- 格式条款风险检测

### 修订追踪
- LLM 生成修订后条款文本
- HTML 差异对比视图（新增绿色/删除红色）
- DOCX Track Changes 下载

### 安全合规
- 敏感信息自动检测（身份证、手机号、邮箱、银行卡号）
- 超出能力范围自动提示转人工
- 所有输出附带免责声明

## License

MIT
