# 8771 test-env deploy client. Run from Windows PowerShell 5.1.
# Usage:
#   .\preview-deploy.ps1 status
#   .\preview-deploy.ps1 build  local-20261104
#   .\preview-deploy.ps1 upload <path-to.tar.gz>
#   .\preview-deploy.ps1 deploy <release-name>
# The private key stays on this machine; only the package bytes go over SSH.

$ErrorActionPreference = 'Stop'
$action = $args[0]
$arg2   = $args[1]

$Key  = 'C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519'
$Dest = 'shilie_deploy@8.156.81.128'
$Repo = 'E:\project\agents\rag-tech-doc-retriever'
$OutDir = Join-Path $Repo 'output\verification\preview-deploy-identity'
$SshArgs = @('-i', $Key, '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
             '-o', 'ConnectTimeout=12', '-o', 'BatchMode=yes', $Dest)

if (-not $action) { Write-Host 'Usage: preview-deploy.ps1 status|build|upload|deploy [arg]'; exit 2 }

if ($action -eq 'status') {
    Write-Host '--- 8771 preview status ---'
    & ssh @SshArgs 'status'
    exit $LASTEXITCODE
}

if ($action -eq 'build') {
    $name = if ($arg2) { $arg2 } else { 'local-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
    $out  = Join-Path $OutDir ($name + '.tar.gz')
    $src  = Join-Path $Repo 'src\rag_tech_retriever'
    if (-not (Test-Path -LiteralPath $src)) { throw "missing $src" }
    $stage = Join-Path $env:TEMP ('shilie-pkg-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Copy-Item -Recurse -Force -LiteralPath $src -Destination (Join-Path $stage 'rag_tech_retriever')
        & tar -czf $out -C $stage 'rag_tech_retriever'
        if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $stage -ErrorAction SilentlyContinue
    }
    Write-Host "built: $out"
    Write-Host "next: .\preview-deploy.ps1 upload `"$out`""
    exit 0
}

if ($action -eq 'upload') {
    if (-not $arg2) { throw 'upload needs <path-to.tar.gz>' }
    if (-not (Test-Path -LiteralPath $arg2)) { throw "missing $arg2" }
    # Feed raw bytes to ssh stdin via cmd.exe type (PS 5.1 pipeline corrupts binary).
    $cmd = 'type "' + $arg2 + '" | ssh'
    foreach ($a in $SshArgs) {
        if ($a -match '\s') { $cmd += ' "' + $a + '"' } else { $cmd += ' ' + $a }
    }
    $cmd += ' upload'
    & cmd.exe /c $cmd
    if ($LASTEXITCODE -ne 0) { throw "upload failed (exit $LASTEXITCODE)" }
    Write-Host 'upload OK. next: .\preview-deploy.ps1 deploy <release-name>'
    exit 0
}

if ($action -eq 'deploy') {
    $name = if ($arg2) { $arg2 } else { 'local-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
    if ($name -notmatch '^[A-Za-z0-9._-]+$' -or $name -eq '.' -or $name -eq '..') {
        throw 'release name allows only A-Z a-z 0-9 . _ -'
    }
    Write-Host "deploy $name ..."
    & ssh @SshArgs ('deploy ' + $name)
    if ($LASTEXITCODE -ne 0) { throw "deploy failed (exit $LASTEXITCODE); runner auto-rolled-back" }
    Write-Host 'deploy OK.'
    & ssh @SshArgs 'status'
    exit $LASTEXITCODE
}

Write-Host "unknown action: $action"
exit 2
