param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$EvidenceFile = "backend/release/evidence.local.json",
    [string]$ReportFile = "backend/release/report.local.json",
    [int]$LoadRequests = 100,
    [int]$LoadConcurrency = 10,
    [switch]$SecretScanPassed,
    [switch]$VerifiedBackup
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-TestSuite {
    param([string]$Suite)
    $lines = & python -m unittest discover -s "tests/$Suite" -p "test_*.py" 2>&1
    $exitCode = $LASTEXITCODE
    $lines | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "$Suite test suite failed."
    }
    $matches = [regex]::Matches(($lines -join "`n"), "Ran\s+(\d+)\s+tests?")
    if ($matches.Count -eq 0) {
        throw "Could not determine the $Suite test count."
    }
    return [int]$matches[$matches.Count - 1].Groups[1].Value
}

$commit = (git rev-parse HEAD).Trim()
$branch = (git branch --show-current).Trim()
$clean = -not [bool](git status --porcelain)

Push-Location backend
try {
    python -m compileall -q app tests main.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }
    $unitCount = Invoke-TestSuite -Suite "unit"
    $integrationCount = Invoke-TestSuite -Suite "integration"
    $smokeCount = Invoke-TestSuite -Suite "smoke"
    python -m bandit -q -r app/api app/core app/database app/deployment app/middleware app/observability app/release -ll -ii
    if ($LASTEXITCODE -ne 0) { throw "Bandit failed." }
    python -m pip_audit -r requirements-prod.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency audit failed." }
}
finally {
    Pop-Location
}

docker compose -f compose.backend.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose validation failed." }
docker build --tag mama-ai-backend:release ./backend
if ($LASTEXITCODE -ne 0) { throw "Container build failed." }
docker compose -f compose.backend.yaml run --rm --no-deps backend python -m app.deployment.validation
if ($LASTEXITCODE -ne 0) { throw "Deployment environment validation failed." }
python scripts/backend_smoke_test.py --base-url $BaseUrl
if ($LASTEXITCODE -ne 0) { throw "Live smoke test failed." }

$loadJson = python scripts/backend_load_test.py `
    --url "$BaseUrl/health/ready" `
    --requests $LoadRequests `
    --concurrency $LoadConcurrency `
    --max-error-rate 1 `
    --max-p95-ms 1000
if ($LASTEXITCODE -ne 0) { throw "Load test failed." }
$load = $loadJson | ConvertFrom-Json

$evidence = [ordered]@{
    commit_sha = $commit
    branch = $branch
    unit_tests = $unitCount
    integration_tests = $integrationCount
    smoke_tests = $smokeCount
    compile_passed = $true
    bandit_passed = $true
    dependency_scan_passed = $true
    secret_scan_passed = [bool]$SecretScanPassed
    compose_validation_passed = $true
    container_build_passed = $true
    deployment_validation_passed = $true
    live_smoke_passed = $true
    verified_backup = [bool]$VerifiedBackup
    clean_worktree = $clean
    load_requests = [int]$load.total_requests
    load_error_rate_percent = [double]$load.error_rate_percent
    load_p95_ms = [double]$load.p95_ms
}

$evidence | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $EvidenceFile
python scripts/backend_release_gate.py --evidence $EvidenceFile --output $ReportFile
$gateExitCode = $LASTEXITCODE

Write-Host "Local release report written to $ReportFile"
Write-Host "Secret-scan and backup gates are accepted only when their proof switches were supplied."
exit $gateExitCode
