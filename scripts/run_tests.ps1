$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath "pyproject.toml" -PathType Leaf)) {
    Write-Error "pyproject.toml was not found. Run this script from the project root."
    exit 1
}

Write-Host "Current directory: $(Get-Location)"
uv run pytest -c pyproject.toml tests
exit $LASTEXITCODE
