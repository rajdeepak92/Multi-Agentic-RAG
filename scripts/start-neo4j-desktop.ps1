$ErrorActionPreference = "Stop"

# Project root = one folder above /scripts
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$EnvFile = Join-Path $ProjectRoot ".env"

if (!(Test-Path $EnvFile)) {
    throw ".env file not found at: $EnvFile"
}

# Load .env into current PowerShell process
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()

    if ($line -eq "" -or $line.StartsWith("#")) {
        return
    }

    $parts = $line -split "=", 2

    if ($parts.Count -eq 2) {
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

# Validate required .env values
if (!$env:NEO4J_DESKTOP_EXE) {
    throw "NEO4J_DESKTOP_EXE is missing in .env"
}

if (!(Test-Path $env:NEO4J_DESKTOP_EXE)) {
    throw "Neo4j Desktop EXE not found at: $env:NEO4J_DESKTOP_EXE"
}

if (!$env:NEO4J_DESKTOP_DATA_PATH) {
    throw "NEO4J_DESKTOP_DATA_PATH is missing in .env"
}

# Create D-drive folders if missing
New-Item -ItemType Directory -Force -Path $env:NEO4J_DESKTOP_DATA_PATH | Out-Null
New-Item -ItemType Directory -Force -Path $env:NEO4J_DUMPS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:NEO4J_IMPORT_DIR | Out-Null

Write-Host "Starting Neo4j Desktop..."
Write-Host "Neo4j Desktop EXE: $env:NEO4J_DESKTOP_EXE"
Write-Host "Neo4j data path:   $env:NEO4J_DESKTOP_DATA_PATH"

Start-Process -FilePath $env:NEO4J_DESKTOP_EXE -WorkingDirectory $ProjectRoot