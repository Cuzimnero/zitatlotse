param([string]$Python = "")

$ErrorActionPreference = 'Stop'
$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceBackend = Join-Path $sourceRoot 'backend'
if (-not (Test-Path -LiteralPath (Join-Path $sourceBackend 'server.py'))) {
    throw 'Backend-Dateien fehlen. Bitte das gesamte Quellcode-Archiv entpacken.'
}
# AppData writes from packaged desktop apps can be virtualized into their private
# LocalCache. A profile-root folder stays visible to Zotero and Task Scheduler.
if (-not $env:USERPROFILE) { throw 'USERPROFILE ist nicht verfügbar.' }
$installRoot = Join-Path $env:USERPROFILE '.zitatlotse'
$legacyRoot = Join-Path $env:LOCALAPPDATA 'Zitatlotse'
$legacyBackend = Join-Path $legacyRoot 'backend'
$legacyPython = Join-Path $legacyBackend '.venv\Scripts\python.exe'
$ownedRoots = @($installRoot, $legacyRoot)
if (Test-Path -LiteralPath $legacyPython) {
    $physicalLegacy = & $legacyPython -c 'import sys; from pathlib import Path; print(Path(sys.prefix).resolve().parent.parent)'
    if ($LASTEXITCODE -eq 0 -and $physicalLegacy) { $ownedRoots += "$physicalLegacy" }
}
$targetBackend = Join-Path $installRoot 'backend'
$targetData = Join-Path $targetBackend 'data'
$taskName = 'Zitatlotse Search Service'
$backgroundPython = Join-Path $targetBackend '.venv\Scripts\pythonw.exe'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    $knownExecutables = @($backgroundPython, $legacyPython.Replace('python.exe','pythonw.exe'))
    if (-not ($existingTask.Actions | Where-Object { $_.Execute -in $knownExecutables })) {
        throw 'Der Aufgabenname Zitatlotse Search Service wird von einem anderen Programm verwendet.'
    }
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}
# Stop only installed Zitatlotse Python processes, supervisors before workers.
$ownedProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -and
    ($commandLine = $_.CommandLine) -and ($ownedRoots | Where-Object {
        $commandLine.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0
    }) -and
    $_.CommandLine -match '(launcher|server)\.py'
}
$ownedProcesses | Sort-Object @{Expression={ if ($_.CommandLine -match '--worker|server\.py') { 1 } else { 0 } }} |
    ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $targetBackend, $targetData -Force | Out-Null
# Retain the previous installation as a backup; copy its environment, models and
# index once. A moved venv still uses the existing, stable base Python runtime.
if (Test-Path -LiteralPath $legacyBackend) {
    foreach ($name in @('.venv', 'data')) {
        $legacyPart = Join-Path $legacyBackend $name
        $targetPart = Join-Path $targetBackend $name
        if ($name -eq 'data') {
            foreach ($file in (Get-ChildItem -LiteralPath $legacyPart -ErrorAction SilentlyContinue)) {
                $destination = Join-Path $targetPart $file.Name
                if (-not (Test-Path -LiteralPath $destination)) {
                    Copy-Item -LiteralPath $file.FullName -Destination $destination -Recurse
                }
            }
        } elseif ((Test-Path -LiteralPath $legacyPart) -and -not (Test-Path -LiteralPath $targetPart)) {
            Copy-Item -LiteralPath $legacyPart -Destination $targetPart -Recurse
        }
    }
}
foreach ($name in @('engine.py', 'server.py', 'launcher.py', 'settings.py', 'agent_search.py', 'embedding_models.py', 'provider_models.py', 'evidence_search.py', 'search_activity.py', 'search_scope.py', 'document_relevance.py', 'requirements.txt')) {
    Copy-Item -LiteralPath (Join-Path $sourceBackend $name) -Destination (Join-Path $targetBackend $name) -Force
}
Copy-Item -LiteralPath (Join-Path $sourceRoot 'Start-Zitatlotse.ps1') -Destination (Join-Path $installRoot 'Start-Zitatlotse.ps1') -Force

# Existing indexes and downloaded model weights are migrated once. Updates keep the installed data.
$oldData = Join-Path $sourceBackend 'data'
if ((Test-Path -LiteralPath $oldData) -and
    ([IO.Path]::GetFullPath($oldData) -ne [IO.Path]::GetFullPath($targetData))) {
    foreach ($name in @('quotes.sqlite', 'settings.json')) {
        $from = Join-Path $oldData $name
        $to = Join-Path $targetData $name
        if ((Test-Path -LiteralPath $from) -and -not (Test-Path -LiteralPath $to)) {
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
    $oldModels = Join-Path $oldData 'models'
    $newModels = Join-Path $targetData 'models'
    if ((Test-Path -LiteralPath $oldModels) -and -not (Test-Path -LiteralPath $newModels)) {
        Write-Host 'Übernehme bereits geladene Modelle. Dies kann einige Minuten dauern.'
        Copy-Item -LiteralPath $oldModels -Destination $newModels -Recurse
    }
}

$prepareArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    (Join-Path $installRoot 'Start-Zitatlotse.ps1'), '-PrepareOnly')
if ($Python) { $prepareArgs += @('-Python', $Python) }
& $powerShell @prepareArgs
if ($LASTEXITCODE -ne 0) { throw 'Python-Umgebung konnte nicht vorbereitet werden. Details: backend\data\setup.log' }

$startup = [Environment]::GetFolderPath('Startup')
New-Item -ItemType Directory -Path $startup -Force | Out-Null
$shortcutPath = Join-Path $startup 'Zitatlotse.lnk'
$workerArguments = '"' + (Join-Path $targetBackend 'launcher.py') + '" --supervise'
$userIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$autostartMode = 'scheduled_task'
try {
    $action = New-ScheduledTaskAction -Execute $backgroundPython -Argument $workerArguments -WorkingDirectory $targetBackend
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userIdentity
    $trigger.Delay = 'PT10S'
    $principal = New-ScheduledTaskPrincipal -UserId $userIdentity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $oldRun = (Get-ItemProperty -LiteralPath $runKey -Name 'Zitatlotse' -ErrorAction SilentlyContinue).Zitatlotse
    if ($oldRun -and ($ownedRoots | Where-Object { $oldRun.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })) {
        Remove-ItemProperty -LiteralPath $runKey -Name 'Zitatlotse'
    }
} catch {
    # A restricted Windows account can still register its own logon launcher.
    $autostartMode = 'user_run'
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -LiteralPath $runKey -Name 'Zitatlotse' -Value ('"' + $backgroundPython + '" ' + $workerArguments)
    Write-Warning 'Windows-Aufgabe nicht verfügbar; Autostart im aktuellen Benutzerprofil eingerichtet.'
}
@{mode=$autostartMode;user=$userIdentity;executable=$backgroundPython;arguments=$workerArguments} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $targetData 'autostart.json') -Encoding UTF8
if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }

$listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if (-not $owner -or -not $owner.CommandLine -or
        -not ($ownedRoots | Where-Object { $owner.CommandLine.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }) -or
        $owner.CommandLine -notmatch '(launcher|server)\.py') {
        throw 'Port 8765 wird von einem anderen Programm verwendet. Der Suchdienst wurde nicht ersetzt.'
    }
    Stop-Process -Id $owner.ProcessId -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
}
if ($autostartMode -eq 'scheduled_task') { Start-ScheduledTask -TaskName $taskName }
else { Start-Process -FilePath $backgroundPython -ArgumentList $workerArguments -WorkingDirectory $targetBackend -WindowStyle Hidden }
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
        if ($health.ok -and $health.service -eq 'zitatlotse') { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "Der installierte Suchdienst antwortet nicht. Details: $targetData\service.log" }
Write-Host "Zitatlotse ist fest installiert unter: $installRoot"
Write-Host 'Der Suchdienst startet bei jeder Windows-Anmeldung automatisch und startet fehlgeschlagene Worker erneut.'
Write-Host 'Beim ersten Start werden gegebenenfalls Python-Pakete und Modelle installiert.'
