param(
    [Parameter(Mandatory = $true)]
    [string]$ImageTag,
    [string]$ComposeFile = "compose.backend.yaml"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

docker compose -f $ComposeFile exec -T backend `
    python -m app.database.recovery_cli backup --reason pre_deployment_rollback

$env:MAMA_IMAGE_TAG = $ImageTag
docker compose -f $ComposeFile pull backend
docker compose -f $ComposeFile up -d --no-build backend

$containerId = docker compose -f $ComposeFile ps -q backend
$deadline = (Get-Date).AddMinutes(3)
do {
    $health = docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId
    if ($health -eq "healthy") { break }
    if ($health -eq "unhealthy" -or (Get-Date) -gt $deadline) {
        docker compose -f $ComposeFile logs --tail=200 backend
        throw "Rollback image did not become healthy."
    }
    Start-Sleep -Seconds 5
} while ($true)

python scripts/backend_smoke_test.py --base-url http://127.0.0.1:8000
Write-Host "Mama AI backend rollback completed."
