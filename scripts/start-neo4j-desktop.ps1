$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$EnvFile = Join-Path $ProjectRoot ".env"

if (!(Test-Path $EnvFile)) {
    throw ".env file not found at: $EnvFile"
}

function Read-DotEnv {
    param([string]$Path)

    $config = @{}

    foreach ($rawLine in Get-Content $Path) {
        $line = $rawLine.Trim()

        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        if ($line.StartsWith("#")) {
            continue
        }

        $parts = $line -split "=", 2

        if ($parts.Count -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            $config[$name] = $value
        }
    }

    return $config
}

function Get-ConfigValue {
    param(
        [hashtable]$Config,
        [string]$Name,
        [string]$DefaultValue = "",
        [bool]$Required = $true
    )

    if ($Config.ContainsKey($Name) -and $Config[$Name]) {
        return $Config[$Name]
    }

    if ($Required) {
        throw "$Name is missing in .env"
    }

    return $DefaultValue
}

function Resolve-ConfiguredPath {
    param(
        [string]$Value,
        [string]$BasePath
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return (Resolve-Path $Value).Path
    }

    return (Resolve-Path (Join-Path $BasePath $Value)).Path
}

function Test-Port {
    param(
        [string]$HostName,
        [int]$Port
    )

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $success = $async.AsyncWaitHandle.WaitOne(1000, $false)

        if ($success) {
            $client.EndConnect($async)
            $client.Close()
            return $true
        }

        $client.Close()
        return $false
    }
    catch {
        return $false
    }
}

function Wait-ForPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSeconds = 120
    )

    Write-Host "Waiting for $HostName`:$Port ..."

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()

    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-Port -HostName $HostName -Port $Port) {
            Write-Host "Port $Port is ready."
            return $true
        }

        Start-Sleep -Seconds 2
    }

    return $false
}

function Invoke-FrameworkGraphCheck {
    $UvCommand = Get-Command "uv" -ErrorAction SilentlyContinue

    if (!$UvCommand) {
        Write-Host ""
        Write-Host "WARN uv was not found on PATH; skipped framework graph-check."
        return $true
    }

    Write-Host ""
    Write-Host "Validating Neo4j credentials with multi-agentic-rag graph-check..."

    Push-Location $ProjectRoot
    try {
        & uv run multi-agentic-rag graph-check
        $GraphCheckExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($GraphCheckExitCode -ne 0) {
        Write-Host ""
        Write-Host "Neo4j ports are open, but framework graph-check failed."
        Write-Host "Check NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, and NEO4J_DATABASE in .env."
        return $false
    }

    return $true
}

function Show-RunnerLog {
    param([string]$RunnerLog)

    Write-Host "------------------------------------------------------------"
    if (Test-Path $RunnerLog) {
        Get-Content $RunnerLog -Tail 100
    }
    else {
        Write-Host "Runner log not found: $RunnerLog"
    }
    Write-Host "------------------------------------------------------------"
}

$Config = Read-DotEnv -Path $EnvFile

$Neo4jDbmsHome = Resolve-ConfiguredPath `
    -Value (Get-ConfigValue -Config $Config -Name "NEO4J_DBMS_HOME") `
    -BasePath $ProjectRoot
$Neo4jJavaHome = Resolve-ConfiguredPath `
    -Value (Get-ConfigValue -Config $Config -Name "NEO4J_JAVA_HOME") `
    -BasePath $ProjectRoot

$Neo4jHost = Get-ConfigValue -Config $Config -Name "NEO4J_HOST" -DefaultValue "127.0.0.1" -Required $false
$BoltPort = [int](Get-ConfigValue -Config $Config -Name "NEO4J_BOLT_PORT" -DefaultValue "7687" -Required $false)
$BrowserPort = [int](Get-ConfigValue -Config $Config -Name "NEO4J_BROWSER_PORT" -DefaultValue "7474" -Required $false)

$Neo4jBat = Join-Path $Neo4jDbmsHome "bin\neo4j.bat"
$JavaExe = Join-Path $Neo4jJavaHome "bin\java.exe"

if (!(Test-Path $Neo4jBat)) {
    throw "neo4j.bat not found at: $Neo4jBat"
}

if (!(Test-Path $JavaExe)) {
    throw "java.exe not found at: $JavaExe"
}

Write-Host ""
Write-Host "Checking Neo4j status..."
Write-Host "DBMS Home:   $Neo4jDbmsHome"
Write-Host "JAVA_HOME:   $Neo4jJavaHome"
Write-Host "Browser URL: http://$Neo4jHost`:$BrowserPort"
Write-Host "Bolt URI:    bolt://$Neo4jHost`:$BoltPort"

$BrowserRunning = Test-Port -HostName $Neo4jHost -Port $BrowserPort
$BoltRunning = Test-Port -HostName $Neo4jHost -Port $BoltPort

if ($BrowserRunning -and $BoltRunning) {
    if (!(Invoke-FrameworkGraphCheck)) {
        exit 1
    }

    Write-Host ""
    Write-Host "Neo4j is already running."
    exit 0
}

$RuntimeDir = Join-Path $ProjectRoot "neo4j\runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

$RunnerScript = Join-Path $RuntimeDir "neo4j-console-runner.ps1"
$RunnerLog = Join-Path $RuntimeDir "neo4j-console-runner.log"

@"
`$ErrorActionPreference = "Stop"

`$env:JAVA_HOME = "$Neo4jJavaHome"
`$env:PATH = "$Neo4jJavaHome\bin;`$env:PATH"

Set-Location "$Neo4jDbmsHome"

"`$(Get-Date -Format o) Starting Neo4j console..." | Out-File -FilePath "$RunnerLog" -Append -Encoding utf8
& "$Neo4jBat" console *>> "$RunnerLog"
"`$(Get-Date -Format o) Neo4j console stopped." | Out-File -FilePath "$RunnerLog" -Append -Encoding utf8
"@ | Set-Content -Path $RunnerScript -Encoding utf8

Write-Host ""
Write-Host "Starting Neo4j in console mode..."
Write-Host "Runner: $RunnerScript"
Write-Host "Log:    $RunnerLog"

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$RunnerScript`"" `
    -WindowStyle Hidden

$BoltReady = Wait-ForPort -HostName $Neo4jHost -Port $BoltPort -TimeoutSeconds 120
$BrowserReady = Wait-ForPort -HostName $Neo4jHost -Port $BrowserPort -TimeoutSeconds 120

if ($BoltReady -and $BrowserReady) {
    if (!(Invoke-FrameworkGraphCheck)) {
        Show-RunnerLog -RunnerLog $RunnerLog
        exit 1
    }

    Write-Host ""
    Write-Host "Neo4j started successfully."
    Write-Host "Browser: http://$Neo4jHost`:$BrowserPort"
    Write-Host "Bolt:    bolt://$Neo4jHost`:$BoltPort"
    Write-Host ""
    Write-Host "Keep the hidden Neo4j PowerShell window running."
    exit 0
}

Write-Host ""
Write-Host "Neo4j did not open required ports."
Write-Host "DBMS Home: $Neo4jDbmsHome"
Write-Host "JAVA_HOME: $Neo4jJavaHome"
Write-Host "Browser:   http://$Neo4jHost`:$BrowserPort"
Write-Host "Bolt:      bolt://$Neo4jHost`:$BoltPort"
Write-Host ""
Write-Host "Last log lines:"
Show-RunnerLog -RunnerLog $RunnerLog
exit 1
