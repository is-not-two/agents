param([switch]$SkipDatabase, [switch]$Background, [switch]$BuildOnly, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) { throw 'Node/npm is required to build Vue.' }
$frontend = Join-Path $PSScriptRoot 'shilie'
$vueTarget = Join-Path $PSScriptRoot 'src\rag_tech_retriever\api\static\vue'
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\vite\bin\vite.js'))) {
    throw 'Vue dependencies are missing. Run npm ci --prefix shilie first.'
}
# Vite clears only its dedicated output; do not follow junctions.
$part = $vueTarget
while ($part -ne $PSScriptRoot) {
    if ((Test-Path -LiteralPath $part) -and ((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Vue output directory must not be redirected by a link.'
    }
    $part = Split-Path -Parent $part
}
& $npm.Source --prefix $frontend run build -- --base /static/vue/ --outDir $vueTarget --emptyOutDir
if ($LASTEXITCODE -ne 0) { throw 'Vue build failed; the server was not started.' }
$entryHtml = Get-Content -LiteralPath (Join-Path $vueTarget 'index.html') -Raw
if ($entryHtml -notmatch 'src="(/static/vue/assets/[A-Za-z0-9_.-]+\.js)"') { throw 'Vue homepage entry is missing.' }
$entryAsset = $Matches[1].Substring('/static/vue/'.Length)
if (-not (Test-Path -LiteralPath (Join-Path $vueTarget $entryAsset) -PathType Leaf)) { throw 'Vue homepage asset is missing.' }
Write-Host "Vue runtime built: $vueTarget"
if ($BuildOnly) { return }

if (-not $PythonExe) { $PythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$env:RAG_PROJECT_ROOT = $PSScriptRoot
$env:PROJECT_ROOT = $PSScriptRoot
if (-not $SkipDatabase) {
    docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        $desktopCandidates = @('F:\Program Files\Docker\Docker Desktop.exe', 'C:\Program Files\Docker\Docker\Docker Desktop.exe')
        $desktopPath = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $desktopPath) { throw '未找到 Docker Desktop，请先启动 Docker 后重试。' }
        Write-Host '正在启动 Docker Desktop，数据库内容会保留。'
        Start-Process -FilePath "$env:WINDIR\explorer.exe" -ArgumentList ('"' + $desktopPath + '"') -WindowStyle Hidden
        $engineReady = $false
        for ($dockerAttempt = 0; $dockerAttempt -lt 30; $dockerAttempt++) {
            Start-Sleep -Seconds 2
            docker info --format '{{.ServerVersion}}' *> $null
            if ($LASTEXITCODE -eq 0) { $engineReady = $true; break }
        }
        if (-not $engineReady) { throw 'Docker 引擎尚未就绪；请检查 Docker Desktop 后重试，不要重置数据。' }
    }
    docker compose up -d --wait db
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败，请检查 Docker Desktop' }
}
$webPort = & $PythonExe -c "from rag_tech_retriever.common.config_loader import ConfigLoader; c=ConfigLoader.load_default(); w=ConfigLoader(c.settings_path.parent/'web.yaml'); print(c.env('WEB_PORT',str(w.get('web.port',8766))))"
if ($LASTEXITCODE -ne 0) { throw '无法读取 Web 配置' }
$webAddress = "http://127.0.0.1:$webPort"
Write-Host "时列工作台：$webAddress"
if (-not $Background) {
    & $PythonExe (Join-Path $PSScriptRoot 'scripts\v2e_start_api.py')
    exit $LASTEXITCODE
}
if (Get-NetTCPConnection -LocalPort ([int]$webPort) -State Listen -ErrorAction SilentlyContinue) {
    try {
        $existingHealth = Invoke-RestMethod "$webAddress/health" -TimeoutSec 2
        $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($existingHealth.pid)"
        $expectedEntry = Join-Path $PSScriptRoot 'scripts\v2e_start_api.py'
        $existingHome = Invoke-WebRequest "$webAddress/" -TimeoutSec 2 -UseBasicParsing
        if ($existingProcess.CommandLine -and $existingProcess.CommandLine.Contains($expectedEntry) -and
            $existingHome.Content -match 'src="/static/vue/assets/') {
            Write-Host '当前项目已经运行，可直接打开上面的地址。'
            return
        }
    } catch { }
    throw "端口 $webPort 已被占用，请先停止现有服务"
}
New-Item -ItemType Directory -Path 'output\web' -Force | Out-Null
$serverEntry = Join-Path $PSScriptRoot 'scripts\v2e_start_api.py'
$launchedWeb = Start-Process -FilePath $PythonExe -ArgumentList @('"' + $serverEntry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'output\web\server-stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'output\web\server-stderr.log') -PassThru
$healthReply = $null
for ($startupAttempt = 0; $startupAttempt -lt 20; $startupAttempt++) {
    try { $healthReply = Invoke-RestMethod "$webAddress/health" -TimeoutSec 1; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $healthReply -or -not $healthReply.pid) { throw '服务未就绪，请查看 output/web/server-stderr.log' }
$home = Invoke-WebRequest "$webAddress/" -TimeoutSec 3 -UseBasicParsing
if ($home.Content -notmatch 'src="/static/vue/assets/') { throw '后端未提供 Vue 首页，请检查构建和运行路径。' }
@{ app_pid = $healthReply.pid; launcher_pid = $launchedWeb.Id; root = $PSScriptRoot; url = $webAddress; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath 'output\web\runtime.json' -Encoding utf8
Write-Host '已在后台运行。停止：./stop-web.ps1'
