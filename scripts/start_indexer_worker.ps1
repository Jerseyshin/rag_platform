$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $ProjectRoot "backend"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}

Write-Host "Starting RAG indexer worker..."
Write-Host "Backend: $BackendDir"
Write-Host "Command: $Python -m app.worker.indexer"
Write-Host "Log file: $BackendDir\logs\indexer_worker.log"

Push-Location $BackendDir
try {
    & $Python -m app.worker.indexer
}
finally {
    Pop-Location
}
