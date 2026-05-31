@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set HF_ENDPOINT=https://hf-mirror.com
echo ========================================
echo 法务审查 Agent v2.5 - 快速启动
echo ========================================
echo.

REM 从 .env 文件加载配置
set "SCRIPT_DIR=%~dp0"
for /f "usebackq tokens=1,* delims==" %%a in ("%SCRIPT_DIR%.env") do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" if not "%%a"=="" set "%%a=%%b"
)

REM 检查必要配置
if "%LLM_API_KEY%"=="" (
    echo [错误] 未配置 LLM_API_KEY，请在 .env 文件中设置
    pause
    exit /b 1
)

echo [配置] LLM API Base: %LLM_API_BASE%
echo [配置] LLM Model: %LLM_MODEL%
echo.
echo [启动] 正在启动...
echo [提示] 启动后请访问 http://localhost:7860
echo [提示] 按 Ctrl+C 可以停止服务
echo ========================================
echo.

cd /d "%SCRIPT_DIR%"
python app.py

pause
