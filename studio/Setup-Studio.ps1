param([string]$PythonExe = '', [switch]$RebuildFrontend)
$ErrorActionPreference = 'Stop'
$StudioRoot = $PSScriptRoot
$StudioPython = Join-Path $StudioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $StudioPython)) {
    if ($PythonExe) {
        & $PythonExe -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ required.' }
        & $PythonExe -m venv (Join-Path $StudioRoot '.venv')
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12+ or supply -PythonExe.' }
        & py -3 -m venv (Join-Path $StudioRoot '.venv')
    } else {
        & python -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12+ or supply -PythonExe.' }
        & python -m venv (Join-Path $StudioRoot '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create studio/.venv.' }
}
& $StudioPython -m pip install --disable-pip-version-check -r (Join-Path $StudioRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $StudioPython -m pip install --disable-pip-version-check --no-deps -e (Split-Path -Parent $StudioRoot)
if ($LASTEXITCODE -ne 0) { throw 'MD2DOC Core package installation failed.' }
if ($RebuildFrontend -or -not (Test-Path -LiteralPath (Join-Path $StudioRoot 'frontend\build\index.html'))) {
    $PnpmVersion = '11.25.0'
    $PnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    $UseInstalledPnpm = $false
    if ($PnpmCommand) {
        $InstalledPnpmVersion = & $PnpmCommand.Source --version
        $UseInstalledPnpm = $LASTEXITCODE -eq 0 -and $InstalledPnpmVersion -eq $PnpmVersion
    }
    if (-not $UseInstalledPnpm -and -not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) {
        throw 'Install Node.js 22.12+ (including npm/npx), or pnpm 11.25.0, then rerun Setup-Studio.ps1.'
    }
    Push-Location (Join-Path $StudioRoot 'frontend')
    try {
        if ($UseInstalledPnpm) { & $PnpmCommand.Source install --frozen-lockfile }
        else { & npx.cmd --yes "pnpm@$PnpmVersion" install --frozen-lockfile }
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        if ($UseInstalledPnpm) { & $PnpmCommand.Source build }
        else { & npx.cmd --yes "pnpm@$PnpmVersion" build }
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
Write-Host 'Studio is ready. Run studio/Start-Studio.ps1.'
