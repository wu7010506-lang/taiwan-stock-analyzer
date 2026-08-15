$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $PSScriptRoot
$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$pythonPath = Join-Path $userProfilePath ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$runtimePath = Join-Path $projectPath "work\pytest-runtime"
$tempPath = Join-Path $projectPath "work\pytest-temp"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python runtime not found: $pythonPath"
}

if (-not (Test-Path -LiteralPath (Join-Path $runtimePath "pytest\__init__.py"))) {
    & $pythonPath -m pip install --target $runtimePath `
        "pytest>=8,<10" "fastapi>=0.115,<1" "httpx>=0.27,<1" "pydantic-settings>=2.6,<3"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$env:PYTHONPATH = "$runtimePath;$projectPath"
Set-Location -LiteralPath $projectPath
& $pythonPath -m pytest -q -p no:cacheprovider --basetemp $tempPath @args
exit $LASTEXITCODE
