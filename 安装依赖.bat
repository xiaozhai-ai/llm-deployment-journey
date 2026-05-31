@echo off
chcp 65001 >nul
echo ========================================
echo 法务审查 Agent v2.5 - 依赖安装
echo ========================================
echo.
echo [提示] 此脚本只需运行一次
echo [提示] 安装完成后请使用"启动.bat"快速启动
echo.
echo 正在安装依赖，请耐心等待...
echo.

pip install "gradio>=5.0.0,<6.0.0" python-docx pdfplumber python-multipart python-Levenshtein lxml pyyaml requests pydantic

echo.
echo ========================================
echo 安装完成！
echo 现在可以双击"启动.bat"快速启动了
echo ========================================
pause
