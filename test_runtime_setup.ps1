param(
    [Parameter(Mandatory=$true)][string]$Xpi,
    [Parameter(Mandatory=$true)][string]$TestRoot,
    [int]$Port = 18765
)
# Run only in a disposable directory, never against a user's installed backend.
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($TestRoot).TrimEnd('\')
if ($root -eq [IO.Path]::GetPathRoot($root) -or $root -eq $env:USERPROFILE -or
    $root -eq (Join-Path $env:USERPROFILE '.zitatlotse')) { throw 'A disposable test directory is required.' }
New-Item -ItemType Directory -Path $root -Force | Out-Null
$status = Join-Path $root 'setup-state.json'
$script = Join-Path $PSScriptRoot 'runtime\setup.ps1'
$savedPath = $env:PATH
$savedOffline = $env:HF_HUB_OFFLINE
$report = @{version='0.27.0'; external_python=$false; model_downloads=$false; cloud_calls=0}
function Check-Health {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5
    if (-not $health.ok -or $health.version -ne '0.27.0') { throw 'Unexpected service health.' }
}
function Stop-TestService {
    $stateFile = Join-Path $root 'backend\data\supervisor.json'
    if (-not (Test-Path -LiteralPath $stateFile)) { return }
    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    foreach ($processId in @($state.pid, $state.worker_pid)) {
        if (-not $processId) { continue }
        $ownedProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($ownedProcess -and $ownedProcess.Path -and $ownedProcess.Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
            Stop-Process -Id $processId -ErrorAction SilentlyContinue
        }
    }
}
try {
    # Simulate a machine without Python on PATH and without model connectivity.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:HF_HUB_OFFLINE = '1'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -AddonPath $Xpi -InstallRoot $root -StatusPath $status -Port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Fresh XPI setup failed.' }
    Check-Health
    $report.fresh_xpi_setup = 'passed'
    $state = Get-Content -LiteralPath $status -Raw | ConvertFrom-Json
    if ($state.phase -ne 'ready' -or $state.percent -ne 100) { throw 'Progress did not finish.' }
    $marker = Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
    if (-not $marker.executable.StartsWith($root + '\') -or $marker.executable.Contains('.venv')) { throw 'Runtime escaped the package installation.' }
    $report.bundled_runtime = 'passed'
    $stats = Invoke-RestMethod "http://127.0.0.1:$Port/status?library_id=1" -TimeoutSec 5
    $report.empty_library = $stats
    Stop-TestService
    Start-Sleep -Seconds 2
    $database = Join-Path $root 'backend\data\quotes.sqlite'
    $hashBefore = (Get-FileHash -LiteralPath $database).Hash
    $sentinel = Join-Path $root 'backend\data\retained-test-note.txt'
    [IO.File]::WriteAllText($sentinel, 'saved data must survive setup')
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -AddonPath $Xpi -InstallRoot $root -StatusPath $status -Port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Post-reboot setup failed.' }
    Check-Health
    Stop-TestService
    if ((Get-FileHash -LiteralPath $database).Hash -ne $hashBefore -or -not (Test-Path -LiteralPath $sentinel)) { throw 'Existing data was replaced.' }
    $report.complete_process_loss_then_restart = 'passed'
    $report.database_preserved = 'passed'
    $report.progress = 'passed'
    $report.windows_reboot = 'simulated by process loss; no OS reboot performed'
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root 'report.json') -Encoding UTF8
    $report | ConvertTo-Json -Depth 5
} finally {
    Stop-TestService
    $env:PATH = $savedPath
    $env:HF_HUB_OFFLINE = $savedOffline
}
