$ErrorActionPreference = "Stop"

$stateFile = Join-Path $env:TEMP "secall-opencode-local.json"
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Host "seCall OpenCode Studio is not running."
    exit 0
}

$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
foreach ($processId in @($state.api_pid, $state.frontend_pid)) {
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
        $ErrorActionPreference = $previousPreference
    }
}

Remove-Item -LiteralPath $stateFile -Force
Write-Host "seCall OpenCode Studio stopped."
