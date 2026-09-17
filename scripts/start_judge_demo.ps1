[CmdletBinding()]
param(
    [switch]$Reset,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.judge-demo.yml'
$stateFile = Join-Path $repoRoot '.env.judge-real.state'

function New-RandomHex {
    param([int]$ByteCount = 32)

    $bytes = [byte[]]::new($ByteCount)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function New-JudgeDemoState {
    $content = @(
        "JUDGE_DEMO_EVIDENCE_SIGNING_KEY=$(New-RandomHex 32)"
        "JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID=judge-demo-$(New-RandomHex 8)"
    )
    # ASCII avoids the UTF-8 BOM emitted by Windows PowerShell 5.1, which
    # Docker Compose would otherwise treat as part of the first variable name.
    Set-Content -LiteralPath $stateFile -Value $content -Encoding ascii
}

function Read-JudgeDemoState {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $stateFile) {
        if ($line -match '^([A-Z0-9_]+)=([a-z0-9-]+)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    if ($values['JUDGE_DEMO_EVIDENCE_SIGNING_KEY'] -notmatch '^[a-f0-9]{64}$' -or
        $values['JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID'] -notmatch '^judge-demo-[a-f0-9]{16}$') {
        throw "Judge-demo state is invalid. Remove '$stateFile' only together with a volume reset."
    }
    return $values
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is required. Install it, start it, and run this launcher again.'
}

$port = if ($env:JUDGE_DEMO_PORT) { $env:JUDGE_DEMO_PORT } else { '8080' }
$parsedPort = 0
if (-not [int]::TryParse($port, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
    throw 'JUDGE_DEMO_PORT must be an integer from 1 through 65535.'
}

$bindAddress = if ($env:JUDGE_DEMO_BIND_ADDRESS) { $env:JUDGE_DEMO_BIND_ADDRESS } else { '0.0.0.0' }
$parsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($bindAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'JUDGE_DEMO_BIND_ADDRESS must be an IPv4 address.'
}

docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Compose is unavailable. Start Docker Desktop and try again.'
}

if (-not (Test-Path -LiteralPath $stateFile)) {
    New-JudgeDemoState
}
$state = Read-JudgeDemoState

$runtimeFile = [System.IO.Path]::GetTempFileName()
try {
    $runtimeValues = @(
        "JUDGE_DEMO_POSTGRES_PASSWORD=$(New-RandomHex 32)"
        "JUDGE_DEMO_SESSION_SECRET=$(New-RandomHex 32)"
        "JUDGE_DEMO_EVIDENCE_SIGNING_KEY=$($state['JUDGE_DEMO_EVIDENCE_SIGNING_KEY'])"
        "JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID=$($state['JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID'])"
        "JUDGE_DEMO_BIND_ADDRESS=$bindAddress"
        "JUDGE_DEMO_PORT=$parsedPort"
    )
    Set-Content -LiteralPath $runtimeFile -Value $runtimeValues -Encoding ascii

    if ($Reset) {
        Write-Host 'Reset requested: removing only the EvidenceGate judge-demo containers and data volume.'
        docker compose --env-file $runtimeFile -f $composeFile down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'Judge-demo reset failed.' }
        Remove-Item -LiteralPath $stateFile -Force
        New-JudgeDemoState
        $state = Read-JudgeDemoState
        $runtimeValues[2] = "JUDGE_DEMO_EVIDENCE_SIGNING_KEY=$($state['JUDGE_DEMO_EVIDENCE_SIGNING_KEY'])"
        $runtimeValues[3] = "JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID=$($state['JUDGE_DEMO_EVIDENCE_SIGNING_KEY_ID'])"
        Set-Content -LiteralPath $runtimeFile -Value $runtimeValues -Encoding ascii
    }

    $upArguments = @('compose', '--env-file', $runtimeFile, '-f', $composeFile, 'up', '--detach', '--wait')
    if ($Offline) {
        $upArguments += '--no-build'
    }
    else {
        $upArguments += '--build'
    }
    docker @upArguments
    if ($LASTEXITCODE -ne 0) { throw 'Judge-demo containers did not become ready.' }
    docker compose --env-file $runtimeFile -f $composeFile exec -T backend python -c "import json,urllib.request; ready=json.load(urllib.request.urlopen('http://frontend:5173/ready',timeout=5)); snapshot=json.load(urllib.request.urlopen('http://frontend:5173/api/v1/research/recorded-source',timeout=20)); assert ready.get('status')=='ready' and snapshot.get('content_checksums_valid') is True and snapshot.get('evidence_classification',{}).get('operational_authority')=='NONE'"
    if ($LASTEXITCODE -ne 0) { throw 'Judge-demo gateway smoke test failed.' }

    $gatewayAddress = if ($bindAddress -eq '0.0.0.0') { '127.0.0.1' } else { $bindAddress }
    $gatewayUrl = "http://${gatewayAddress}:$parsedPort"
    $readyResponse = Invoke-RestMethod -Uri "$gatewayUrl/ready" -TimeoutSec 10
    $snapshotResponse = Invoke-RestMethod -Uri "$gatewayUrl/api/v1/research/recorded-source" -TimeoutSec 20
    if ($readyResponse.status -ne 'ready' -or $snapshotResponse.content_checksums_valid -ne $true) {
        throw 'Published judge gateway did not return a valid recorded source.'
    }
}
finally {
    if (Test-Path -LiteralPath $runtimeFile) {
        Remove-Item -LiteralPath $runtimeFile -Force
    }
}

$addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.InterfaceAlias -notmatch 'Loopback|vEthernet|WSL|Docker'
    } |
    Select-Object -ExpandProperty IPAddress -Unique

Write-Output ''
Write-Output "EvidenceGate is ready on this computer: http://localhost:$parsedPort"
if ($addresses.Count -gt 0) {
    Write-Output 'Judges on the same trusted Wi-Fi or Ethernet network can open:'
    foreach ($address in $addresses) {
        Write-Output "  http://${address}:$parsedPort"
    }
}
Write-Output 'Use this LAN mode only on a trusted local network; it intentionally has no sign-in.'
Write-Output 'Data persists across ordinary stops and restarts.'
Write-Output 'See docs/JUDGE_DEMO.md for the stop command.'
Write-Output 'Reset only its saved data and signing identity with: .\scripts\start_judge_demo.ps1 -Reset'
Write-Output 'After the initial build, use -Offline on judging day to forbid rebuilding.'
