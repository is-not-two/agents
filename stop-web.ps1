$ErrorActionPreference = 'Stop'
$runtimePath = Join-Path $PSScriptRoot 'output\web\runtime.json'
if (-not (Test-Path -LiteralPath $runtimePath)) { Write-Host '没有本工作台的后台运行记录'; exit 0 }
$webRuntime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$webProcessId = [int]$webRuntime.app_pid
$ownedWebProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $webProcessId"
if (-not $ownedWebProcess) { Write-Host '工作台已停止'; exit 0 }
if (-not $ownedWebProcess.CommandLine.Contains($PSScriptRoot) -or -not $ownedWebProcess.CommandLine.Contains('v2e_start_api.py')) {
    throw 'PID 已属于其他进程，拒绝停止'
}
Stop-Process -Id $webProcessId
Write-Host '时列工作台已停止，数据库与内容保留。'
