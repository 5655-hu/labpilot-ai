# 一键以「真实后端」模式启动：前端构建 + 后端同源托管，一个进程同时服务页面和 API。
#
# 用法：  .\一键启动.ps1
# 打开：  http://localhost:8000        （本机）
#         http://<本机局域网IP>:8000   （同一 WiFi 下的别人也能打开）
#
# 说明：这样起的是真正的后端，上传 CSV、跑审计、出报告都是实时计算。

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "[1/3] 构建前端（同源模式：请求直达 /api）" -ForegroundColor Cyan
Set-Location (Join-Path $root 'frontend')
$env:VITE_API_SAME_ORIGIN = '1'
npm run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败，已中止' }

Write-Host "[2/3] 准备静态目录" -ForegroundColor Cyan
$distPath = (Resolve-Path (Join-Path $root 'frontend\dist')).Path
$env:FRONTEND_DIR = $distPath
Write-Host "      FRONTEND_DIR = $distPath"

Write-Host "[3/3] 启动服务" -ForegroundColor Cyan
Set-Location (Join-Path $root 'backend')

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' } |
    Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "本机访问：   http://localhost:8000" -ForegroundColor Green
if ($lanIp) { Write-Host "局域网访问： http://$lanIp`:8000" -ForegroundColor Green }
Write-Host "健康检查：   http://localhost:8000/health" -ForegroundColor Green
Write-Host "按 Ctrl+C 停止" -ForegroundColor DarkGray
Write-Host ""

.\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000
