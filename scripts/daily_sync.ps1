$ErrorActionPreference = "Stop"
$projectPath = Split-Path -Parent $PSScriptRoot
$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$pythonPath = Join-Path $userProfilePath ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

Set-Location -LiteralPath $projectPath
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python runtime not found: $pythonPath"
}
& $pythonPath -m scripts.daily_sync
exit $LASTEXITCODE
