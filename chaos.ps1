# PowerShell wrapper for chaos.py.
# Run from the repo root as `.\chaos status` (PowerShell auto-resolves
# the .ps1 extension via PATHEXT).
# Permanent alias: see the README "Quickstart" section.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& python (Join-Path $here 'chaos.py') @args
exit $LASTEXITCODE
