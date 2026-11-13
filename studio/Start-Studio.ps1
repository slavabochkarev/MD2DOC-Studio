param([int]$Port = 8731, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$StudioPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $StudioPython)) { throw 'Run studio/Setup-Studio.ps1 first.' }
$StudioArgs = @((Join-Path $PSScriptRoot 'start.py'), '--port', $Port)
if ($NoBrowser) { $StudioArgs += '--no-browser' }
& $StudioPython @StudioArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
