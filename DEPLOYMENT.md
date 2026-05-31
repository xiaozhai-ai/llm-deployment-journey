# 法务审查 Agent v2.0 - 部署指南

## Hugging Face Spaces 部署

### 步骤

1. **创建 Space**
   - 登录 [Hugging Face](https://huggingface.co/)
   - 点击 **New Space**
   - SDK: **Gradio**
   - Python Version: **3.11**

2. **上传文件**
   ```bash
   git clone https://huggingface.co/spaces/<用户名>/legal-review-agent
   cd legal-review-agent
   # 复制所有项目文件
   git add . && git commit -m "Deploy v2.0" && git push
   ```

3. **配置 Secrets** (Settings → Repository secrets)
   - `LLM_API_KEY`: 你的 LLM API 密钥
   - `LLM_API_BASE`: API 端点（可选）
   - `LLM_MODEL`: 模型名称（可选，默认 qwen-plus）

## 支持的 LLM API

任何兼容 OpenAI API 格式的服务：

### 通义千问（推荐）
```
LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

### 其他服务
配置对应的 `LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL` 即可。

## 本地开发

```bash
# 虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依赖
pip install -r requirements.txt

# 运行
export LLM_API_KEY="your-key"
python app.py
```

## 审查策略配置

在 `config/playbooks/` 下创建 YAML 文件即可添加新策略：

```yaml
id: "my_custom_strategy"
name: "自定义策略"
description: "策略描述"
role: "party_a"  # party_a / party_b / neutral
strictness: "high"  # low / medium / high / strict
focus_areas:
  - "违约责任"
  - "争议解决"
risk_weight_adjustments:
  "MISSING_CLAUSE_001":
    level: "critical"
    reason: "调整原因"
custom_prompts:
  risk_analysis: |
    自定义 LLM prompt
```

## 自定义风险规则

编辑 `config/legal_rules.yaml` 添加规则：

```yaml
risk_rules:
  - id: "CUSTOM_001"
    name: "自定义风险"
    category: "风险类别"
    risk_level: "high"
    description: "描述"
    legal_basis: "法律依据"
    suggestion: "修改建议"
    applicable_types: ["contract", "agreement"]
```

## 日志

运行后会在 `logs/` 目录生成：
- `audit.log` - 操作审计日志（JSON 格式）
- `llm_trace.log` - LLM 推理链路日志（JSON 格式）

## 常见问题

**Q: ChromaDB 安装失败？**
A: 确保 Python >= 3.8，可尝试 `pip install chromadb --no-cache-dir`

**Q: HF Spaces 超时？**
A: 免费版有 60 秒限制，大文件建议升级到付费 Space 或调整 `LLM_MODEL` 为更快的模型

**Q: 如何更新法规知识库？**
A: 编辑 `config/legal_kb.yaml` 添加新法条，重启后自动向量化
