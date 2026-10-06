param([Parameter(Mandatory=$true)][string]$Output,
      [ValidateRange(0,10)][int]$ColdCycles=0,
      [switch]$TestEarlyCrash,
      [switch]$TestSchedulerRecovery,
      [switch]$TestLocalSearch,
      [switch]$TestScheduledTrigger,
      [switch]$SupplementaryOnly,
      [ValidateRange(1,2147483647)][int]$LibraryId=1,
      [string]$DinoAttachmentKey='',
      [string[]]$TestAttachmentKeys=@())

# Real Windows startup/recovery test. Stops only this installed service, restores
# its registered autostart at the end, and never logs document text or API keys.
$ErrorActionPreference = 'Stop'
if ($TestLocalSearch -and (-not $DinoAttachmentKey -or $TestAttachmentKeys.Count -eq 0)) {
    throw 'For local search, provide -DinoAttachmentKey and -TestAttachmentKeys for your own DINO/MiVOLO/distillation test PDFs.'
}
$outputParent = Split-Path -Parent ([IO.Path]::GetFullPath($Output))
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$installRoot = Join-Path $env:USERPROFILE '.zitatlotse'
$backend = Join-Path $installRoot 'backend'
$backgroundPython = Join-Path $backend '.venv\Scripts\pythonw.exe'
$consolePython = Join-Path $backend '.venv\Scripts\python.exe'
$arguments = '"' + (Join-Path $backend 'launcher.py') + '" --supervise'
$taskName = 'Zitatlotse Search Service'
$primaryTaskName = $taskName
$temporaryTaskName = $null
$autostart = Get-Content -LiteralPath (Join-Path $backend 'data\autostart.json') -Raw | ConvertFrom-Json
$nodeExecutable = (Get-Command node.exe -ErrorAction Stop).Source

function Assert-Result([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-Counts {
    $counts = & $consolePython -c 'import sys,sqlite3,json; from pathlib import Path; db=sqlite3.connect("file:"+Path(sys.argv[1]).as_posix()+"?mode=ro",uri=True); print(json.dumps({**{name:db.execute("SELECT COUNT(*) FROM "+name).fetchone()[0] for name in ("documents","chunks","saved_quotes")},"embedding_model":db.execute("SELECT value FROM index_metadata WHERE key=?",("embedding_model",)).fetchone()[0]}))' (Join-Path $backend 'data\quotes.sqlite')
    Assert-Result ($LASTEXITCODE -eq 0) 'Cannot read the installed index counts'
    return $counts | ConvertFrom-Json
}

function Stop-OwnService([switch]$Crash) {
    if ($autostart.mode -eq 'scheduled_task') {
        $task = Get-ScheduledTask -TaskName $taskName
        Assert-Result ($task.Actions.Execute -eq $backgroundPython) 'Unexpected scheduled task owner'
        if (-not $Crash) { Stop-ScheduledTask -TaskName $taskName }
    }
    $owned = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -and
        $_.CommandLine.IndexOf($backend, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $_.CommandLine -match '(launcher|server)\.py'
    }
    $owned | Sort-Object @{Expression={ if ($_.CommandLine -match '--worker|server\.py') { 1 } else { 0 } }} |
        ForEach-Object {
            if ($Crash) {
                # Stop-Process uses a forced-stop exit code. Here explicitly
                # simulate a failing program with exit code 1 instead.
                $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ProcessId)"
                if ($current -and $current.CommandLine -like ('*' + $backend + '*launcher.py*')) {
                    [ZitatlotseCrashSimulator]::Crash($current.ProcessId)
                }
            } else { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
        }
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'Owned service did not release port 8765'
}

function Start-RegisteredService {
    if ($autostart.mode -eq 'scheduled_task') { Start-ScheduledTask -TaskName $taskName }
    else { Start-Process -FilePath $backgroundPython -ArgumentList $arguments -WorkingDirectory $backend -WindowStyle Hidden }
}

function Wait-Healthy([int]$TimeoutSeconds=45) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
            if ($health.ok -and $health.service -eq 'zitatlotse' -and $health.version -eq '0.26.3') {
                return $watch.Elapsed.TotalSeconds
            }
        } catch { }
        Start-Sleep -Milliseconds 250
    }
    throw "Service did not become healthy within $TimeoutSeconds seconds"
}

$report = [ordered]@{version='0.26.3';created_at=(Get-Date).ToString('o');install_root=$installRoot;
    autostart_mode=$autostart.mode;actual_pc_reboot_tested=$false;before=(Get-Counts)}
try {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    if (-not $SupplementaryOnly) {
    Stop-OwnService
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Start-RegisteredService
    $null = Wait-Healthy
    $report.registered_cold_start_seconds = [Math]::Round($watch.Elapsed.TotalSeconds,3)
    $state = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
    $supervisorID = $state.pid
    Assert-Result ($state.state -eq 'running') 'Supervisor did not start a worker'
    Write-Host 'Registered cold start: OK'

    $duplicate = Start-Process -FilePath $backgroundPython -ArgumentList $arguments -WorkingDirectory $env:TEMP -WindowStyle Hidden -PassThru
    Assert-Result ($duplicate.WaitForExit(10000)) 'Duplicate launcher must exit instead of keeping another supervisor'
    Assert-Result ($duplicate.ExitCode -eq 0) 'Duplicate launcher failed'
    $sameState = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
    Assert-Result ($sameState.pid -eq $supervisorID) 'Duplicate start replaced the supervisor'
    $report.duplicate_start_passed = $true
    Write-Host 'Duplicate launcher: OK'

    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen | Select-Object -First 1
    $workerID = $listener.OwningProcess
    $worker = Get-CimInstance Win32_Process -Filter "ProcessId=$workerID"
    Assert-Result ($worker.CommandLine -like ('*' + $backend + '*') -and $worker.CommandLine -match '--worker') 'Port owner is not our worker'
    $ancestor = $worker
    $related = $false
    for ($depth=0; $depth -lt 5 -and $ancestor; $depth++) {
        if ($ancestor.ProcessId -eq $supervisorID) { $related = $true; break }
        $ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$($ancestor.ParentProcessId)"
    }
    Assert-Result $related 'Worker does not belong to the installed supervisor'
    $watch.Restart()
    Stop-Process -Id $workerID
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener -and $listener.OwningProcess -ne $workerID) { break }
        Start-Sleep -Milliseconds 500
    }
    $null = Wait-Healthy
    $recovered = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
    Assert-Result ($recovered.pid -eq $supervisorID -and $listener.OwningProcess -ne $workerID) 'Worker crash did not recover under the same supervisor'
    $report.worker_recovery_seconds = [Math]::Round($watch.Elapsed.TotalSeconds,3)
    Write-Host 'Worker crash recovery: OK'

    Stop-OwnService
    $originalPath = $env:PATH
    try {
        $env:PATH = Join-Path $env:WINDIR 'System32'
        & $nodeExecutable (Join-Path $PSScriptRoot 'smoke_service_start.js') ($Output + '.menu.json')
        Assert-Result ($LASTEXITCODE -eq 0) 'Shipped menu startup function failed'
    } finally { $env:PATH = $originalPath }
    $menu = Get-Content -LiteralPath ($Output + '.menu.json') -Raw | ConvertFrom-Json
    Assert-Result ($menu.launches -eq 1) 'Cold concurrent menu requests did not launch exactly once'
    $report.menu_cold_start = $menu
    Write-Host 'Menu cold start without venv PATH: OK'

    $log = [IO.File]::Open((Join-Path $backend 'data\service.log'), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    $log.Dispose()
    $report.service_log_not_exclusively_locked = $true
    }
    $report.cold_cycles = @()
    for ($cycle=1; $cycle -le $ColdCycles; $cycle++) {
        $oldState = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        Stop-OwnService
        $remaining = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like ('*' + $backend + '*launcher.py*')
        })
        Assert-Result ($remaining.Count -eq 0) 'A previous process survived the simulated shutdown'
        $lockRemains = Test-Path -LiteralPath (Join-Path $backend 'data\service.lock')
        Assert-Result $lockRemains 'Expected to test a persistent lock file left after shutdown'
        $watch.Restart()
        Start-RegisteredService
        $null = Wait-Healthy
        $fresh = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        Assert-Result ($fresh.pid -ne $oldState.pid -and $fresh.worker_pid -ne $oldState.worker_pid) 'Cold start reused a previous process'
        $report.cold_cycles += @{cycle=$cycle;seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3);
            new_supervisor=$true;new_worker=$true;previous_processes=0;stale_lock_reused=$lockRemains;passed=$true}
        Write-Host "Simulated shutdown/start cycle $cycle`: OK"
    }

    if ($TestEarlyCrash) {
        $oldState = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        Stop-OwnService
        # Deterministic transient startup fault: retain a read-only exclusive
        # handle briefly. File contents are untouched; new SQLite opens fail.
        $databaseLease = [IO.File]::Open((Join-Path $backend 'data\quotes.sqlite'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        $earlyState = $null
        try {
            Start-RegisteredService
            $watch.Restart()
            while ($watch.Elapsed.TotalSeconds -lt 20) {
                $candidate = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
                if ($candidate.pid -ne $oldState.pid -and $candidate.state -eq 'retrying' -and $candidate.exit_code -ne 0) {
                    $earlyState = $candidate
                    break
                }
                Start-Sleep -Milliseconds 100
            }
            Assert-Result ([bool]$earlyState) 'Did not observe the injected failure before the first startup completed'
            $listening = $false
            try { $listening = [bool](Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 1).ok } catch { }
            Assert-Result (-not $listening) 'Database fault did not prevent first availability'
        } finally { $databaseLease.Dispose() }
        $watch.Restart()
        $null = Wait-Healthy
        $restarted = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        Assert-Result ($restarted.pid -eq $earlyState.pid) 'Early startup failure did not recover under the same supervisor'
        $report.early_startup_failure = @{fault='temporary_read_only_database_lock';before_first_health=$true;
            worker_exit_code=$earlyState.exit_code;seconds_after_release=[Math]::Round($watch.Elapsed.TotalSeconds,3);same_supervisor=$true;passed=$true}
        Write-Host 'Startup failure with temporarily unavailable database: OK'
    }

    if ($TestSchedulerRecovery) {
        if (-not ('ZitatlotseCrashSimulator' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ZitatlotseCrashSimulator {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint id);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static void Crash(uint id) {
        IntPtr handle = OpenProcess(1, false, id);
        if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        try { if (!TerminateProcess(handle, 1)) throw new Win32Exception(Marshal.GetLastWin32Error()); }
        finally { CloseHandle(handle); }
    }
}
'@
        }
        Assert-Result ($autostart.mode -eq 'scheduled_task') 'Scheduler recovery requires a registered Windows task'
        if ($TestScheduledTrigger) {
            $primaryTask = Get-ScheduledTask -TaskName $primaryTaskName
            Assert-Result ($primaryTask.Actions.Execute -eq $backgroundPython) 'Unexpected production task action'
            $originalTaskXML = Export-ScheduledTask -TaskName $primaryTaskName
            Stop-OwnService
            $temporaryTaskName = 'Zitatlotse Boot Test-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
            $triggerAt = (Get-Date).AddSeconds(15)
            $trigger = New-ScheduledTaskTrigger -Once -At $triggerAt
            Register-ScheduledTask -TaskName $temporaryTaskName -Action $primaryTask.Actions -Principal $primaryTask.Principal -Settings $primaryTask.Settings -Trigger $trigger -Description 'Temporary Zitatlotse cold-start test; removed at test completion.' | Out-Null
            $taskName = $temporaryTaskName
            $null = Wait-Healthy -TimeoutSeconds 50
            $info = Get-ScheduledTaskInfo -TaskName $temporaryTaskName
            $report.time_trigger_start = @{trigger_type='one_time';scheduled_at=$triggerAt.ToString('o');
                actual_started_at=$info.LastRunTime.ToString('o');ready_after_start_seconds=[Math]::Round(((Get-Date)-$info.LastRunTime).TotalSeconds,3);passed=$true}
            Write-Host 'Actual automated Windows time-trigger startup: OK'
        }
        $oldState = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        $watch = [Diagnostics.Stopwatch]::StartNew()
        # Do not Stop-ScheduledTask here. Windows must observe the non-zero exit
        # and execute its registered RestartOnFailure policy itself.
        Stop-OwnService -Crash
        Write-Host 'All service processes terminated; waiting for Windows automatic task recovery (one-minute retry).'
        try { $null = Wait-Healthy -TimeoutSeconds 100 }
        catch {
            $report.scheduler_recovery = @{seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3);exit_code=1;
                manual_restart=$false;passed=$false;error=$_.Exception.Message}
            $report.scheduler_observation = Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult
            throw
        }
        $restarted = Get-Content -LiteralPath (Join-Path $backend 'data\supervisor.json') -Raw | ConvertFrom-Json
        Assert-Result ($restarted.pid -ne $oldState.pid) 'Windows did not create a new supervisor'
        $report.scheduler_recovery = @{seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3);exit_code=1;new_supervisor=$true;manual_restart=$false;passed=$true}
        Write-Host 'Windows automatic recovery of entire service: OK'
    }

    if ($TestLocalSearch) {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $report.local_search = @()
        foreach ($case in @(
            @{query='Average';positive=$true},
            @{query='DINO momentum teacher exponential moving average';positive=$true;attachment_keys=@($DinoAttachmentKey)},
            @{query='migraine medication placebo clinical trial efficacy';positive=$false;attachment_keys=$TestAttachmentKeys}
        )) {
            $payload = @{library_id=$LibraryId;query=$case.query;limit=20}
            if ($case.ContainsKey('attachment_keys')) { $payload.attachment_keys = $case.attachment_keys }
            $watch.Restart()
            $result = Invoke-RestMethod 'http://127.0.0.1:8765/search' -Method Post -ContentType 'application/json' -Headers @{'X-Zitatlotse-Client'='1'} -Body ($payload | ConvertTo-Json -Compress) -TimeoutSec 180
            $total = if ($null -ne $result.total_results) { $result.total_results } else { @($result.results).Count }
            Assert-Result (($case.positive -and $total -gt 0) -or (-not $case.positive -and $total -eq 0)) 'Local search after cold start returned unexpected results'
            $report.local_search += @{query=$case.query;library_id=$LibraryId;attachment_keys=$case.attachment_keys;mode='direct';hits=$total;displayed_page_hits=@($result.results).Count;
                seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3);passed=$true}
            Write-Host "Local search after simulated reboot: $($case.query) -> $total hits"
        }
    }
    $report.after = Get-Counts
    Assert-Result (($report.before | ConvertTo-Json -Compress) -eq ($report.after | ConvertTo-Json -Compress)) 'Index or saved quote counts changed'
    $report.passed = $true
} catch {
    $report.passed = $false
    $report.error = $_.Exception.Message
    throw
} finally {
    # Leave Windows responsible for the final daemon, independently of this test.
    Stop-OwnService
    if ($temporaryTaskName) {
        $ownedTask = Get-ScheduledTask -TaskName $temporaryTaskName -ErrorAction SilentlyContinue
        if ($ownedTask -and $ownedTask.Actions.Execute -eq $backgroundPython) {
            Unregister-ScheduledTask -TaskName $temporaryTaskName -Confirm:$false
        }
        $taskName = $primaryTaskName
        $report.temporary_task_removed = -not [bool](Get-ScheduledTask -TaskName $temporaryTaskName -ErrorAction SilentlyContinue)
        $report.production_task_configuration_unchanged = (Export-ScheduledTask -TaskName $primaryTaskName) -eq $originalTaskXML
    }
    Start-RegisteredService
    $null = Wait-Healthy
    $report.after = Get-Counts
    $report.final_health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 5
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Output -Encoding UTF8
}
