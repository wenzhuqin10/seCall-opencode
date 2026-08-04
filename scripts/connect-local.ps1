param(
    [string]$Uri = "secall-opencode://start"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$stateFile = Join-Path $env:TEMP "secall-opencode-local.json"
$python = (Get-Command python.exe -ErrorAction Stop).Source
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

$state = @{}
if (Test-Path -LiteralPath $stateFile) {
    try {
        $savedState = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
        if ($savedState.api_pid) { $state.api_pid = $savedState.api_pid }
        if ($savedState.frontend_pid) { $state.frontend_pid = $savedState.frontend_pid }
    } catch {
        $state = @{}
    }
}

$apiReady = $false
try {
    # Health includes local model/index statistics and can take a few seconds.
    # A generous timeout prevents a second API process from being started while
    # the existing service is still computing its response.
    $apiReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 10).StatusCode -eq 200
} catch {}

if (-not $apiReady) {
    $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "secall_opencode.cli", "serve", "--host", "127.0.0.1", "--port", "8765") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -PassThru
    $state.api_pid = $apiProcess.Id
}

$frontendReady = $false
try {
    $frontendReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000" -TimeoutSec 5).StatusCode -eq 200
} catch {}

if (-not $frontendReady) {
    $frontendProcess = Start-Process `
        -FilePath $npm `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden `
        -PassThru
    $state.frontend_pid = $frontendProcess.Id
}

$state.started_at = (Get-Date).ToString("o")
$state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
