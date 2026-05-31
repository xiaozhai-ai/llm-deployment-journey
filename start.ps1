# 法务审查 Agent v2.5 - PowerShell 启动脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "法务审查 Agent v2.5 - 本地启动脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 从 .env 文件加载配置
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line -split "=", 2
            if ($parts.Length -eq 2) {
                [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
            }
        }
    }
    Write-Host "[配置] 已从 .env 加载配置" -ForegroundColor Green
} else {
    Write-Host "[错误] 未找到 .env 文件，请复制 .env.example 为 .env 并填写配置" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "[配置] LLM API Base: $env:LLM_API_BASE" -ForegroundColor Green
Write-Host "[配置] LLM Model: $env:LLM_MODEL" -ForegroundColor Green
Write-Host "[配置] 最大文件大小: $env:MAX_FILE_SIZE_MB MB" -ForegroundColor Green
Write-Host ""

Write-Host "[启动] 正在启动法务审查 Agent..." -ForegroundColor Yellow
Write-Host "[提示] 启动后请访问 http://localhost:7860" -ForegroundColor Yellow
Write-Host ""

# 切换到脚本所在目录
Set-Location -Path $PSScriptRoot

# 启动应用
python app.py

Write-Host ""
Write-Host "按任意键退出..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
