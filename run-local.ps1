$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts/python.exe'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js 20 or newer is required.'
}
if (-not (Get-Command corepack -ErrorAction SilentlyContinue)) {
    throw 'Corepack is required. Install Node.js 20 or newer.'
}

if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venv
    } else {
        throw 'Python 3.10 or newer is required.'
    }
}

& $python -m pip install -r (Join-Path $root 'backend/requirements-pi.txt')
& corepack yarn --cwd (Join-Path $root 'frontend') install --frozen-lockfile

$backend = $null
$frontend = $null
try {
    $backend = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', '8001') `
        -WorkingDirectory (Join-Path $root 'backend') -PassThru -NoNewWindow
    $frontend = Start-Process -FilePath $env:ComSpec `
        -ArgumentList @('/c', 'corepack yarn --cwd frontend start') `
        -WorkingDirectory $root -PassThru -NoNewWindow

    Write-Host 'ROM Translator is starting at http://localhost:3000'
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Milliseconds 500
    }
    throw 'A local server stopped. Review the output above for details.'
} finally {
    foreach ($process in @($frontend, $backend)) {
        if ($null -ne $process -and -not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F *> $null
        }
    }
}