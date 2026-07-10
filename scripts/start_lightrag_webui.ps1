param(
    [string]$EnvFile = "backend/.env.lightrag-webui"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$EnvPath = Join-Path $ProjectRoot $EnvFile
$ExampleEnvPath = Join-Path $ProjectRoot "backend/.env.lightrag-webui.example"
$ServerPath = Join-Path $ProjectRoot ".venv/Scripts/lightrag-server.exe"

if (-not (Test-Path -LiteralPath $EnvPath)) {
    if (Test-Path -LiteralPath $ExampleEnvPath) {
        Write-Host "Env file not found: $EnvPath"
        Write-Host "Using example env: $ExampleEnvPath"
        $EnvPath = $ExampleEnvPath
    } else {
        throw "Env file not found: $EnvPath"
    }
}

if (-not (Test-Path -LiteralPath $ServerPath)) {
    throw "lightrag-server.exe not found. Install optional deps first: .\.venv\Scripts\pip.exe install -r backend\requirements-lightrag-webui.txt"
}

Get-Content -LiteralPath $EnvPath -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }

    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        return
    }

    $key = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($key) {
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

if ($env:WORKING_DIR -and -not [System.IO.Path]::IsPathRooted($env:WORKING_DIR)) {
    $env:WORKING_DIR = (Join-Path $ProjectRoot $env:WORKING_DIR)
}

Write-Host "Starting LightRAG WebUI..."
Write-Host "URL: http://$env:HOST`:$env:PORT/webui"
Write-Host "WORKING_DIR: $env:WORKING_DIR"

Push-Location $BackendRoot
try {
    & $ServerPath
} finally {
    Pop-Location
}
