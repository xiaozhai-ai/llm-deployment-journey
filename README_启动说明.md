# 法务审查 Agent v2.5 - 快速启动指南

## 📋 快速使用（推荐）

### 首次使用（只需一次）

1. **安装依赖**：双击 `安装依赖.bat`
   - 等待 5-10 分钟完成安装
   - 只需运行一次

2. **快速启动**：双击 `启动.bat`
   - 2-3 秒即可启动完成
   - 访问 http://localhost:7860

### 后续使用

直接双击 `启动.bat` 即可，无需重复安装！

---

##  启动优化说明

### 优化前
- ❌ 每次启动都检查和安装依赖
- ❌ 需要等待 1-2 分钟
- ❌ 网络不好时会卡住

### 优化后
- ✅ 依赖安装和启动分离
- ✅ 快速启动只需 2-3 秒
- ✅ 无需重复下载

---

## 🔧 手动启动（如果需要）

```powershell
cd C:\Users\ZXC\Desktop\legal-review-agent

# 配置环境变量
$env:LLM_API_KEY = "tp-cpsv37w7qrefaera0opszwp8kor2tt5808x9x6smhaza7sci"
$env:LLM_API_BASE = "https://token-plan-cn.xiaomimimo.com/anthropic"
$env:LLM_MODEL = "xiaomi-mimo-v2.5-pro"

# 启动
python app.py
```

---

## 📦 如果依赖安装失败

可以手动逐个安装：

```powershell
pip install "gradio>=5.0.0,<6.0.0"
pip install python-docx
pip install pdfplumber
pip install python-multipart
pip install python-Levenshtein
pip install lxml
pip install pyyaml
pip install requests
pip install pydantic
```

---

## 🎯 测试文件

已准备好测试文件：`test_contract.txt`

启动后上传此文件，测试审查功能！

---

## 💡 常见问题

**Q: 为什么启动还是慢？**
A: 可能是第一次启动需要初始化 ChromaDB 向量库（如果有安装）。这是正常的，后续启动会快很多。

**Q: 如何停止服务？**
A: 在命令行窗口按 `Ctrl+C` 即可。

**Q: 端口被占用怎么办？**
A: 修改 `app.py` 中的端口号，或关闭占用 7860 端口的其他程序。
