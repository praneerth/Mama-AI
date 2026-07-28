param(
    [string]$ImageTag = "latest",
    [string]$ComposeFile = "compose.backend.yaml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "backend/.env")) {
    throw "backend/.env is missing. Create it from backend/.env.example and configure production secrets locally."
}

$env:MAMA_IMAGE_TAG = $ImageTag
Push-Location backend
try {
    python -m compileall -q app tests main.py
    python -m unittest discover -s tests/unit -p "test_deployment_*.py" -v
    python -m unittest discover -s tests/unit -p "test_container_tool_isolation.py" -v
}
finally {
    Pop-Location
}

docker compose -f $ComposeFile config --quiet
docker compose -f $ComposeFile build --pull backend
docker compose -f $ComposeFile run --rm --no-deps backend python -m app.deployment.validation
docker compose -f $ComposeFile up -d backend

$containerId = docker compose -f $ComposeFile ps -q backend
if (-not $containerId) {
    throw "Mama AI backend container was not created."
}

$deadline = (Get-Date).AddMinutes(3)
do {
    $health = docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId
    if ($health -eq "healthy") { break }
    if ($health -eq "unhealthy" -or (Get-Date) -gt $deadline) {
        docker compose -f $ComposeFile logs --tail=200 backend
        throw "Mama AI backend did not become healthy."
    }
    Start-Sleep -Seconds 5
} while ($true)

python scripts/backend_smoke_test.py --base-url http://127.0.0.1:8000
Write-Host "Mama AI backend deployment is healthy."
