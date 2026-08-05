$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
  py -3 -m codex_stats @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  python -m codex_stats @args
} else {
  Write-Host "Python 3.9+ not found. Install Python and add it to PATH."
  exit 1
}
