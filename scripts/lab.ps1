param([ValidateSet('run','check','test','migrate','bootstrap')][string]$Action = 'run', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $labRoot
New-Item -ItemType Directory -Force .local | Out-Null
$labPython = Join-Path $labRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) { throw 'Create .venv and install requirements.lock first; see README.md.' }
$labSecretPath = Join-Path $labRoot '.local\secret.txt'
if (-not $env:LAB_SECRET_KEY) {
    if (-not (Test-Path -LiteralPath $labSecretPath)) {
        & $labPython -c 'import secrets; print(secrets.token_urlsafe(50))' | Set-Content -LiteralPath $labSecretPath -Encoding ascii
    }
    $env:LAB_SECRET_KEY = (Get-Content -LiteralPath $labSecretPath -Raw).Trim()
}
$env:LAB_LOCAL_DEV = '1'
if (-not $env:LAB_DB) { $env:LAB_DB = 'sqlite' }
switch ($Action) {
    'run' { & $labPython web/manage.py runserver "127.0.0.1:$Port" --noreload --insecure }
    'check' { & $labPython web/manage.py check }
    'test' { & $labPython web/manage.py test lab -v 2 }
    'migrate' { & $labPython web/manage.py migrate }
    'bootstrap' { & $labPython web/manage.py bootstrap_lab }
}
if ($LASTEXITCODE -ne 0) { throw "Django command failed with exit code $LASTEXITCODE" }
