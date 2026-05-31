# 部署指南

## Hugging Face Spaces 部署（推荐）

### 1. 创建 Space

1. 登录 [Hugging Face](https://huggingface.co/)
2. 点击 **New Space**
3. 配置：
   - **SDK**: Gradio
   - **Python Version**: 3.11
   - **Space Hardware**: CPU Basic（免费）

### 2. 上传代码

**方式一：Git 推送**
```bash
git clone https://huggingface.co/spaces/<你的用户名>/legal-review-agent
cd legal-review-agent
# 复制项目文件到此目录
git add .
git commit -m "Deploy v2.5"
git push
```

**方式二：网页上传**
- 在 Space 的 **Files** 标签页直接上传项目文件

### 3. 配置环境变量

在 Space 的 **Settings → Repository secrets** 中添加：

| Secret 名称 | 值 | 必需 |
|-------------|-----|:---:|
| `LLM_API_KEY` | 你的 LLM API 密钥 | ✅ |
| `LLM_API_BASE` | API 端点 URL | 可选 |
| `LLM_MODEL` | 模型名称 | 可选 |

**支持的 LLM 提供商：**

| 提供商 | LLM_API_BASE | LLM_MODEL |
|--------|-------------|-----------|
| 通义千问（默认） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 小米 MiMo | `https://api.mimoworks.com/v1` | `mimo-v2.5-pro` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 其他 OpenAI 兼容 | 对应端点 | 对应模型名 |

### 4. 重启 Space

配置完 Secrets 后，点击 **Factory reboot** 重启 Space。

### 5. 验证

- 查看 **Logs** 标签页确认启动成功
- 应看到 `✅ 向量库初始化完成` 和 `Running on local URL: http://0.0.0.0:7860`

### ⚠️ 常见问题

| 问题 | 解决方案 |
|------|----------|
| 启动超时 | 免费 Space 有 60s 限制，首次启动 ChromaDB 下载 ONNX 模型可能超时，重试即可 |
| API 调用失败 | 检查 Secrets 是否正确配置，注意不要有空格 |
| 内存不足 | 免费 Space 内存有限，大文件建议升级或使用外部向量库 |
| 模型不可用 | 先用 `curl` 测试 API 端点连通性 |

---

## Docker 部署

```bash
# 构建镜像
docker build -t legal-review-agent .

# 运行容器
docker run -d \
  -p 7860:7860 \
  --env-file .env \
  --name legal-review \
  legal-review-agent

# 查看日志
docker logs -f legal-review
```

### Docker Compose

```yaml
version: '3.8'
services:
  legal-review:
    build: .
    ports:
      - "7860:7860"
    env_file:
      - .env
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
    restart: unless-stopped
```

---

## 本地开发

```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动
python app.py

# 运行测试
pytest tests/ -v
```
