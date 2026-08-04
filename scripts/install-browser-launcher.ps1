param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$launcher = Join-Path $PSScriptRoot "connect-local.ps1"
$protocolRoot = "HKCU:\Software\Classes\secall-opencode"
$commandKey = Join-Path $protocolRoot "shell\open\command"
$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" "%1"' -f $launcher

New-Item -Path $commandKey -Force | Out-Null
New-ItemProperty -Path $protocolRoot -Name "(default)" -Value "URL:seCall OpenCode Launcher" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $protocolRoot -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $commandKey -Name "(default)" -Value $command -PropertyType String -Force | Out-Null

if (-not $Quiet) {
    Write-Host "Browser launcher installed: secall-opencode://start"
}
