param([ValidateSet('init','start','stop','test','migrate')][string]$Action = 'test', [string]$Bin = 'C:\Program Files\PostgreSQL\18\bin', [int]$Port = 55439)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $labRoot
$labCluster = Join-Path $labRoot '.local\m2a-pg'
$labPasswordFile = Join-Path $labRoot '.local\pg-password.txt'
$labLog = Join-Path $labRoot '.local\postgres.log'
$labPython = Join-Path $labRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $Bin 'pg_ctl.exe'))) { throw 'An existing compatible PostgreSQL installation is required. No installation is automated.' }
if ($Action -eq 'init') {
    if (Test-Path -LiteralPath $labCluster) { throw 'Cluster path already exists; preserving it. Use start/test instead.' }
    New-Item -ItemType Directory -Force .local | Out-Null
    if (-not (Test-Path -LiteralPath $labPasswordFile)) { & $labPython -c 'import secrets; print(secrets.token_urlsafe(40))' | Set-Content -LiteralPath $labPasswordFile -Encoding ascii }
    & (Join-Path $Bin 'initdb.exe') -D $labCluster -U lab_local --auth=scram-sha-256 --pwfile=$labPasswordFile --encoding=UTF8 --locale=C
} elseif ($Action -eq 'start') {
    & (Join-Path $Bin 'pg_ctl.exe') -D $labCluster -l $labLog -o "-h 127.0.0.1 -p $Port" -w start
} elseif ($Action -eq 'stop') {
    & (Join-Path $Bin 'pg_ctl.exe') -D $labCluster -m fast -w stop
} else {
    $env:PGDATABASE = 'hardware_lab_m2a'
    $env:PGUSER = 'lab_local'
    $env:PGPASSWORD = (Get-Content -LiteralPath $labPasswordFile -Raw).Trim()
    $env:PGHOST = '127.0.0.1'
    $env:PGPORT = "$Port"
    $env:LAB_DB = 'postgres'
    if ($Action -eq 'migrate') {
        # Create a dedicated workspace DB only when absent. No existing database is dropped.
        $labExists = & (Join-Path $Bin 'psql.exe') -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='hardware_lab_m2a'"
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL connectivity check failed.' }
        if ($labExists -ne '1') { & (Join-Path $Bin 'createdb.exe') hardware_lab_m2a; if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated database.' } }
    }
    & (Join-Path $PSScriptRoot 'lab.ps1') -Action $Action
}
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL operation failed with code $LASTEXITCODE" }
