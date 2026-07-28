$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
python -m pip install -e $repoRoot --no-build-isolation

Write-Host "安装完成。下一步："
Write-Host '  secall-opencode init --vault "C:\path\to\seCallVault"'
Write-Host "  secall-opencode doctor"
