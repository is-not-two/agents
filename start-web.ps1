param([switch]$SkipDatabase, [switch]$Background)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $SkipDatabase) {
    docker compose up -d --wait db
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败，请检查 Docker Desktop' }
}
$webPort = & '.\.venv\Scripts\python.exe' -c "from rag_tech_retriever.common.config_loader import ConfigLoader; c=ConfigLoader.load_default(); w=ConfigLoader(c.settings_path.parent/'web.yaml'); print(c.env('WEB_PORT',str(w.get('web.port',8766))))"
if ($LASTEXITCODE -ne 0) { throw '无法读取 Web 配置' }
$webAddress = "http://127.0.0.1:$webPort"
Write-Host "时列工作台：$webAddress"
if (-not $Background) {
    & '.\.venv\Scripts\python.exe' 'scripts\v2e_start_api.py'
    exit $LASTEXITCODE
}
if (Get-NetTCPConnection -LocalPort ([int]$webPort) -State Listen -ErrorAction SilentlyContinue) {
    throw "端口 $webPort 已被占用，请先停止现有服务"
}
New-Item -ItemType Directory -Path 'output\web' -Force | Out-Null
$serverEntry = Join-Path $PSScriptRoot 'scripts\v2e_start_api.py'
$launchedWeb = Start-Process -FilePath (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -ArgumentList @('"' + $serverEntry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'output\web\server-stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'output\web\server-stderr.log') -PassThru
$healthReply = $null
for ($startupAttempt = 0; $startupAttempt -lt 20; $startupAttempt++) {
    try { $healthReply = Invoke-RestMethod "$webAddress/health" -TimeoutSec 1; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $healthReply -or -not $healthReply.pid) { throw '服务未就绪，请查看 output/web/server-stderr.log' }
@{ app_pid = $healthReply.pid; launcher_pid = $launchedWeb.Id; root = $PSScriptRoot; url = $webAddress; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath 'output\web\runtime.json' -Encoding utf8
Write-Host '已在后台运行。停止：./stop-web.ps1'
