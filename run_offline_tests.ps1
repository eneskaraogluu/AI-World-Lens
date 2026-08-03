$ErrorActionPreference = "Stop"
$env:PYTHON_DOTENV_DISABLED = "1"
$env:DATABASE_URL = "sqlite://"
$env:OPENAI_API_KEY = "offline-test-placeholder"
$env:GEMINI_API_KEY = "offline-test-placeholder"
$env:RUN_LIVE_API_TESTS = "0"
$env:RUN_REAL_DATABASE_TESTS = "0"
$env:ALLOW_DESTRUCTIVE_DATABASE_TESTS = "0"
$env:RUN_LOCAL_SERVER_TESTS = "0"
$venvSitePackages = Join-Path $PSScriptRoot "venv\Lib\site-packages"
if (Test-Path -LiteralPath $venvSitePackages) {
    $env:PYTHONPATH = (Resolve-Path -LiteralPath $venvSitePackages).Path
}

$python = $null
$pythonPrefix = @()
$requestedPython = $env:AI_WORLD_LENS_PYTHON
if ($requestedPython -and (Test-Path -LiteralPath $requestedPython)) {
    & $requestedPython --version *> $null
    if ($LASTEXITCODE -eq 0) { $python = $requestedPython }
}
$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not $python -and (Test-Path -LiteralPath $venvPython)) {
    & $venvPython --version *> $null
    if ($LASTEXITCODE -eq 0) { $python = $venvPython }
}
if (-not $python) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { $python = $systemPython.Source }
}
if (-not $python) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher -3 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $python = $pythonLauncher.Source
            $pythonPrefix = @("-3")
        }
    }
}
if (-not $python) {
    throw "No usable Python interpreter was found. Activate the project venv and retry."
}
$pythonTests = @(
    "test_data_integrity.py", "test_openai_generator.py", "test_mock.py",
    "test_mock_api.py", "test_queue_worker_session_lifecycle.py",
    "test_presentation_backup.py", "test_presentation_backup_api.py", "test_presentation_migration.py", "test_research_api.py",
    "test_research_campaign_lifecycle.py", "test_research_core.py",
    "test_research_migration.py", "test_vision_failover.py"
)

foreach ($test in $pythonTests) {
    Write-Host "=== $test ==="
    & $python @pythonPrefix $test
    if ($LASTEXITCODE -ne 0) { throw "$test failed with exit code $LASTEXITCODE" }
}

$node = "C:\Program Files\nodejs\node.exe"
if (Test-Path -LiteralPath $node) {
    foreach ($test in @("test_cinema_presentation.js", "test_frontend_integrity.js", "test_failover_frontend.js", "test_presentation_backup_frontend.js", "test_image_fit_frontend.js")) {
        Write-Host "=== $test ==="
        & $node $test
        if ($LASTEXITCODE -ne 0) { throw "$test failed with exit code $LASTEXITCODE" }
    }
}

Write-Host "OFFLINE TEST SUITE: PASS"
