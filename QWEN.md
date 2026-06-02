# 法务审查 Agent

基于 AI 的法律文件自动化风险识别工具，支持合同/协议/隐私政策等多种法律文件。

## 快速概览

```
用户上传文件 → 解析层(parser) → 结构重建(structure) → 风险引擎(risk_engine)
                                                         ↓
                                              LLM 分析(llm_client) + 规则匹配
                                                         ↓
                                              输出层(report/redliner) → UI(app.py)
```

## 技术栈

- Python 3.10+ / Gradio UI
- ChromaDB 向量检索（DashScope text-embedding-v3 API 嵌入）
- LLM: 通义千问 (qwen-plus) 兼容接口
- 部署: Hugging Face Spaces / 本地

## 常用命令

```bash
pip install -r requirements.txt   # 安装依赖
python app.py                     # 启动应用
pytest tests/ -q                  # 运行测试
ruff check . && ruff format --check .  # lint + 格式
```

## 架构分层

### 1. 入口层

```
app.py                    # Gradio 入口：模块初始化 + 界面启动 + 线程管理
```

### 2. 业务编排层（src/ 根）

```
src/agent_loop.py         # Agent 主循环：文件解析 → 风险分析 → 报告生成 流程编排
src/handlers.py           # 业务处理器：Gradio 事件 → agent_loop 桥接
src/task_runner.py        # 后台任务管理：异步任务队列 + 超时控制
```

### 3. 核心模型层（src/core/）

```
src/core/
├── config.py             # 配置管理：环境变量 + 路径 + LLM 参数
├── data_models.py        # 核心数据模型：BBox/LayoutBlock/TableBlock/ClauseNode/PageLayout 等
└── exceptions.py         # 异常体系：LegalReviewError → 各模块子异常
```

### 4. 解析层（src/parsing/）

```
src/parsing/
├── parser.py             # 文档解析器：PDF/DOCX/DOC/TXT 多格式 + OCR 回退
├── scan_detector.py      # 扫描件检测：文本密度 + 图片占比判断
│
├── structure/            # 文档结构重建
│   ├── clause_patterns.py  #   条款标题正则（YAML 可配置）
│   ├── clause_tree.py      #   条款层级树构建
│   ├── cross_page_merger.py #   跨页段落合并
│   └── table_parser.py     #   表格结构化（HTML/pdfplumber/无边框检测）
│
├── layout/               # 版面分析引擎
│   ├── engine.py           #   LayoutEngine 抽象基类 + 工厂
│   ├── paddle_engine.py    #   PaddleOCR PP-StructureV3 实现
│   └── reading_order.py    #   阅读顺序恢复（多栏支持）
│
└── legal_entities/       # 法律实体提取
    ├── metadata.py         #   合同元数据（名称/类型/当事人/管辖）
    ├── amount.py           #   金额（阿拉伯/中文大写/一致性校验）
    ├── date_extractor.py   #   日期（中文/数字/相对日期）
    ├── signature.py        #   签章识别
    ├── revision.py         #   修订追踪（Track Changes + PDF 注释）
    └── definition.py       #   定义引用（"以下简称XXX"）
```

### 5. 分析引擎层（src/analysis/）

```
src/analysis/
├── risk_engine.py        # 风险识别核心：规则匹配 + LLM 分析 + Playbook 策略 + 去重
├── legal_matcher.py      # 法条匹配：向量语义 + 关键词混合检索
├── playbook_manager.py   # 审查策略管理：甲方/乙方/中立/隐私/劳动合同
├── legal_terms.py        # 法律术语库：同义词扩展 + 强制召回表
└── knowledge_freshness.py # 知识库新鲜度检测
```

### 6. LLM & 向量层（src/llm/）

```
src/llm/
├── llm_client.py         # LLM API 客户端：chat + tool-calling + SSE 流式 + 重试
├── vector_store.py       # ChromaDB 向量库：API 嵌入 + 多路召回 + RRF 融合排序 + 降级
├── tool_agent.py         # Tool-Calling Agent：LLM + 工具调用 + 自我反思循环
└── tools/                # 工具集
    ├── base.py           #   工具基类 + 注册表
    ├── legal_search.py   #   法规检索工具
    ├── case_search.py    #   判例检索工具
    └── ambiguity_check.py #   歧义检测工具
```

### 7. 输出层（src/output/）

```
src/output/
├── report.py             # 风险报告生成：Markdown + 结构化 dict
├── redliner.py           # 修订追踪：HTML diff + DOCX Track Changes
├── html_renderers.py     # HTML 渲染工具
└── security.py           # 敏感信息脱敏 + 范围外检测
```

### 8. 基础设施层（src/infra/）

```
src/infra/
├── logger.py             # 日志管理
├── metrics.py            # 指标收集：Token 消耗 + 性能 + 错误率
├── session_store.py      # 会话存储：LRU + TTL 自动过期
├── chat_memory.py        # 对话记忆：会话级上下文 + 追问生成
├── feedback_store.py     # 人工反馈存储：误报标记 → Few-shot 注入
└── utils.py              # 通用工具函数
```

### 9. UI 层

```
src/ui/                   # Gradio 界面组件
```

### 10. 配置文件

```
config/
├── legal_rules.yaml      # 风险规则（条件匹配 + 缺失条款检测）
├── legal_kb.yaml         # 法律法规知识库（→ vector_store）
├── case_law.yaml         # 判例库（→ vector_store）
├── clause_patterns.yml   # 条款标题正则模式（可自定义）
├── playbooks/            # 审查策略
│   ├── neutral.yaml      #   中立
│   ├── party_a.yaml      #   甲方
│   ├── party_b.yaml      #   乙方
│   ├── privacy.yaml      #   隐私合规
│   └── labor.yaml        #   劳动合同
└── feedback/             # 用户反馈数据
```

## 核心数据流

```
PDF/DOCX/DOC/TXT
    │
    ▼
parsing/parser.py (解析) ──→ ParsedDocument {text, metadata, tables[], clauses[]}
    │
    ├── parsing/structure/ (结构重建) ──→ ClauseNode 树 + 跨页合并 + 表格矩阵
    ├── parsing/legal_entities/ (实体提取) ──→ 金额/日期/签章/定义
    └── parsing/layout/ (版面分析，OCR 路径) ──→ PageLayout {blocks[], tables[]}
    │
    ▼
analysis/risk_engine.py (风险分析)
    ├── 规则匹配 (legal_rules.yaml)
    ├── LLM 分析 (分段并行 + tool-calling)
    └── Playbook 策略调整
    │
    ▼
RiskAnalysisResult {risks[], metadata, analysis_time}
    │
    ├── output/report.py ──→ Markdown 报告
    ├── output/redliner.py ──→ HTML diff + DOCX
    └── analysis/legal_matcher.py ──→ 法条溯源
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | API 密钥 (必需) |
| `LLM_API_BASE` | API URL (默认通义千问) |
| `LLM_MODEL` | 模型名 (默认 qwen-plus) |
| `EMBEDDING_API_BASE` | 嵌入 API 端点 (默认 DashScope) |
| `EMBEDDING_API_KEY` | 嵌入 API 密钥 (空则回退 LLM_API_KEY) |
| `EMBEDDING_MODEL` | 嵌入模型名 (默认 text-embedding-v3) |

## CI/CD 约定

**每次修改代码前，必须确保以下三项全部通过：**

```bash
ruff check .          # lint 检查
ruff format --check . # 格式检查
pytest tests/ -q      # 全量测试
```

如有 lint 错误，先尝试 `ruff check --fix .` 自动修复，再 `ruff format .` 格式化。

- CI 工作流: `.github/workflows/ci.yml` (push/PR 自动触发)
- 部署工作流: `.github/workflows/deploy.yml` (push main → HF Spaces)
- Lint 规则: E/W/F/I/UP/B/SIM，详见 `pyproject.toml`
- 测试框架: pytest + pytest-asyncio，asyncio_mode=auto
