FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 创建非 root 用户
RUN useradd -m -r appuser && mkdir -p logs config/feedback && chown -R appuser:appuser /app

# 复制项目文件
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 7860

CMD ["python", "app.py"]
