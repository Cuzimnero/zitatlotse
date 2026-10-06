param([string]$Python = "", [switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
$dataDir = Join-Path $backend 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
Start-Transcript -Path (Join-Path $dataDir 'setup.log') -Append | Out-Null
$env:HF_HOME = Join-Path $dataDir 'models'
$env:MPLCONFIGDIR = Join-Path $dataDir 'matplotlib'

if (-not (Test-Path -LiteralPath $venvPython)) {
    $candidates = @()
    if ($Python) { $candidates += $Python }
    $candidates += @('py', 'python')
    $workingPython = $null
    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$version" -match 'Python 3\.(1[0-9]|[2-9][0-9])') {
                $workingPython = $candidate
                break
            }
        } catch { }
    }
    if (-not $workingPython) {
        throw 'Kein funktionsfähiges Python 3.10+ gefunden. Python installieren oder -Python C:\Pfad\python.exe angeben.'
    }
    & $workingPython -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python-Umgebung konnte nicht erstellt werden.' }
}

if ($PrepareOnly) {
    $packages = & $venvPython -m pip list --format=json | ConvertFrom-Json
    $installed = $packages.Name
    $transformers = $packages | Where-Object { $_.Name -eq 'transformers' } | Select-Object -First 1
    $missing = @('pymupdf', 'sentence-transformers', 'bert-score', 'keyring', 'transformers') |
        Where-Object { $_ -notin $installed }
    if ($missing -or ($transformers -and ([version]$transformers.Version -lt [version]'4.51' -or
                                         [version]$transformers.Version -ge [version]'5.0'))) {
        Write-Host 'Installiere die benötigten Python-Pakete. Das kann einige Minuten dauern.'
        & $venvPython -m pip install -r (Join-Path $backend 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Installation der Python-Pakete fehlgeschlagen.' }
    }
    Write-Host "Python-Umgebung bereit: $venvPython"
    Stop-Transcript | Out-Null
    exit 0
}

Stop-Transcript | Out-Null
$backgroundPython = Join-Path $backend '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $backgroundPython)) { throw 'pythonw.exe fehlt. Bitte Install-Zitatlotse.ps1 ausführen.' }
$workerArguments = '"' + (Join-Path $backend 'launcher.py') + '" --supervise'
Start-Process -FilePath $backgroundPython -ArgumentList $workerArguments -WorkingDirectory $backend -WindowStyle Hidden
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
        if ($health.ok -and ($health.service -eq 'zitatlotse' -or $health.version)) {
            Write-Host 'Zitatlotse-Suchdienst ist bereit.'
            exit 0
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}
throw 'Suchdienst wurde gestartet, antwortet aber noch nicht. Details: backend\data\service.log'
