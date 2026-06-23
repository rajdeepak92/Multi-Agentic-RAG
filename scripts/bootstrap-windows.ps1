param(
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[bootstrap] $Message"
}

$pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null)
if (-not $pythonVersion) {
    throw "Python 3.12+ is required and python was not found on PATH."
}

$parts = $pythonVersion.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 12)) {
    throw "Python 3.12+ is required. Found $pythonVersion."
}
Write-Step "Python $pythonVersion detected."

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install uv, then rerun this script."
}
Write-Step "uv detected."

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Step "Created .env from .env.example."
} else {
    Write-Step ".env already exists or .env.example is missing; no overwrite performed."
}

if (-not (Test-Path "base_config.json") -and (Test-Path "base_config.example.json")) {
    Copy-Item "base_config.example.json" "base_config.json"
    Write-Step "Created base_config.json from base_config.example.json."
} else {
    Write-Step "base_config.json already exists or example is missing; no overwrite performed."
}

New-Item -ItemType Directory -Force "documents", ".global_cache", "generated" | Out-Null
Write-Step "Runtime directories are present."

if (-not $SkipSync) {
    Write-Step "Running uv sync --dev --extra cpu --link-mode=copy."
    uv sync --dev --extra cpu --link-mode=copy
}

Write-Host ""
Write-Host "Configure these services before running health checks:"
Write-Host "- PostgreSQL: set POSTGRES_DSN in .env and run uv run --no-sync alembic upgrade head"
Write-Host "- Neo4j: set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD in .env"
Write-Host "- Chroma: local persistence uses .global_cache/vectorstore/chroma"
Write-Host ""
Write-Host "Next checks:"
Write-Host "uv run --no-sync multi-agentic-rag db-check"
Write-Host "uv run --no-sync multi-agentic-rag chroma-check"
Write-Host "uv run --no-sync multi-agentic-rag graph-check"
Write-Host "uv run --no-sync multi-agentic-rag health-check"
