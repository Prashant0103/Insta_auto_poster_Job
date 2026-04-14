$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$pythonPath = Join-Path $ProjectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $pythonPath)) {
    $pythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path $pythonPath)) {
    $pythonPath = 'python'
}

& $pythonPath (Join-Path $ProjectRoot 'main.py')
exit $LASTEXITCODE