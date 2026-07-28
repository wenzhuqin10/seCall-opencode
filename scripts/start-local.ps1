$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$stateFile = Join-Path $env:TEMP "secall-opencode-local.json"

$python = (Get-Command python.exe -ErrorAction Stop).Source
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

$apiProcess = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "secall_opencode.cli", "serve", "--host", "127.0.0.1", "--port", "8765") `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -PassThru

$apiReady = $false
for ($attempt = 0; $attempt -lt 5; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 10
        if ($response.StatusCode -eq 200) {
            $apiReady = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $apiReady) {
    Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
    throw "Local API failed to start. Run secall-opencode doctor."
}

$frontendProcess = Start-Process `
    -FilePath $npm `
    -ArgumentList @("run", "dev") `
    -WorkingDirectory $frontendRoot `
    -WindowStyle Hidden `
    -PassThru

@{
    api_pid = $apiProcess.Id
    frontend_pid = $frontendProcess.Id
    started_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

$frontendReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000" -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $frontendReady) {
    throw "Frontend failed to start. Run npm run dev in the frontend directory."
}

Start-Process "http://localhost:3000"

Write-Host "seCall OpenCode Studio is running:"
Write-Host "  UI:  http://localhost:3000"
Write-Host "  API: http://127.0.0.1:8765"
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1"
