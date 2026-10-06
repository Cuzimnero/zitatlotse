param(
    [Parameter(Mandatory=$true)][string]$AddonPath,
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$StatusPath,
    [int]$Port = 8765,
    [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
New-Item -ItemType Directory -Path $root -Force | Out-Null
$status = [IO.Path]::GetFullPath($StatusPath)
if (-not $status.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Status path must stay inside the installation.'
}

function Write-State([string]$Phase, [int]$Percent, [string]$ErrorText = '') {
    $value = @{phase=$Phase; percent=$Percent; error=$ErrorText; updated_at=[DateTime]::UtcNow.ToString('o')}
    $temporary = $status + '.tmp'
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $status -Force
}

function Expand-SafeZip([string]$Archive, [string]$Destination, [int]$Start, [int]$End) {
    $destinationRoot = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $index = 0
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $destinationRoot $entry.FullName))
            if (-not $target.StartsWith($destinationRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Archive contains a path outside the installation.'
            }
            if ($entry.FullName.EndsWith('/')) { New-Item -ItemType Directory -Path $target -Force | Out-Null }
            else {
                New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            }
            $index++
            if ($index % 80 -eq 0) { Write-State 'extracting' ($Start + [int](($End-$Start)*$index/$zip.Entries.Count)) }
        }
    } finally { $zip.Dispose() }
}

function Stop-InstalledService([string]$Backend) {
    # Use our own process record; WMI/CIM access can be disabled on a normal PC.
    $stateFile = Join-Path $Backend 'data\supervisor.json'
    if (-not (Test-Path -LiteralPath $stateFile)) { return }
    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    foreach ($processId in @($state.pid, $state.worker_pid)) {
        if (-not $processId -or "$processId" -notmatch '^\d+$') { continue }
        $ownedProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if (-not $ownedProcess -or -not $ownedProcess.Path) { continue }
        $path = [IO.Path]::GetFullPath($ownedProcess.Path)
        if (($path.StartsWith($root + '\runtime\', [StringComparison]::OrdinalIgnoreCase) -or
             $path.StartsWith($Backend + '\.venv\', [StringComparison]::OrdinalIgnoreCase)) -and
            $ownedProcess.ProcessName -in @('python','pythonw') -and
            $ownedProcess.StartTime.ToUniversalTime() -le ([DateTime]::Parse($state.updated_at).ToUniversalTime().AddSeconds(2))) {
            Stop-Process -Id $processId -ErrorAction Stop
        }
    }
}

$package = $null
$lock = $null
try {
    # Cross-process lock: two Zotero windows or profiles share one installation.
    $lock = [IO.File]::Open((Join-Path $root 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Write-State 'checking' 2
    $addon = [IO.Path]::GetFullPath($AddonPath)
    if (Test-Path -LiteralPath $addon -PathType Leaf) {
        $package = [IO.Compression.ZipFile]::OpenRead($addon)
        $metaEntry = $package.GetEntry('runtime/manifest.json')
        if (-not $metaEntry) { throw 'The XPI does not contain a runtime manifest.' }
        $reader = New-Object IO.StreamReader($metaEntry.Open())
        try { $metadata = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    } else {
        $metadata = Get-Content -LiteralPath (Join-Path $addon 'runtime\manifest.json') -Raw | ConvertFrom-Json
    }
    if ($metadata.platform -ne 'win-x64' -or -not [Environment]::Is64BitOperatingSystem) {
        throw 'This release requires Windows x64.'
    }
    foreach ($hash in @($metadata.runtime_sha256, $metadata.backend_sha256)) {
        if ($hash -notmatch '^[a-f0-9]{64}$') { throw 'Invalid runtime manifest checksum.' }
    }
    if ($metadata.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version.' }
    $runtimeId = $metadata.runtime_sha256.Substring(0,16)
    $runtimePath = Join-Path $root ('runtime\' + $runtimeId)
    $backend = Join-Path $root 'backend'
    $markerPath = Join-Path $root 'installation.json'
    $marker = $null
    if (Test-Path -LiteralPath $markerPath) { $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json }
    $runtimeReady = Test-Path -LiteralPath (Join-Path $runtimePath '.complete')
    $backendReady = $marker -and $marker.backend_sha256 -eq $metadata.backend_sha256 -and
        (Test-Path -LiteralPath (Join-Path $backend 'launcher.py')) -and
        (Test-Path -LiteralPath (Join-Path $backend 'server.py'))

    $staging = Join-Path $root ('staging\' + $metadata.version)
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    foreach ($component in @('runtime','backend')) {
        if (($component -eq 'runtime' -and $runtimeReady) -or ($component -eq 'backend' -and $backendReady)) { continue }
        $entryName = if ($component -eq 'runtime') { 'runtime/python.zip' } else { 'runtime/backend.zip' }
        $zipPath = Join-Path $staging ($component + '.zip')
        if ($package) {
            $entry = $package.GetEntry($entryName)
            if (-not $entry) { throw "Missing bundled component: $entryName" }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $zipPath, $true)
        } else { Copy-Item -LiteralPath (Join-Path $addon $entryName) -Destination $zipPath -Force }
        $expected = if ($component -eq 'runtime') { $metadata.runtime_sha256 } else { $metadata.backend_sha256 }
        if ((Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw "Checksum mismatch: $component"
        }
        if ($component -eq 'runtime') {
            Expand-SafeZip $zipPath $runtimePath 5 72
            if (-not (Test-Path -LiteralPath (Join-Path $runtimePath 'pythonw.exe'))) { throw 'Bundled Python is incomplete.' }
            [IO.File]::WriteAllText((Join-Path $runtimePath '.complete'), $metadata.runtime_sha256)
        } else {
            # Update only code files; the existing database/cache stays in backend/data.
            $newBackend = Join-Path $staging 'backend'
            Expand-SafeZip $zipPath $newBackend 73 80
            Stop-InstalledService $backend
            New-Item -ItemType Directory -Path $backend -Force | Out-Null
            foreach ($file in (Get-ChildItem -LiteralPath $newBackend -File)) {
                Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $backend $file.Name) -Force
            }
        }
    }
    $python = Join-Path $runtimePath 'python.exe'
    Write-State 'verifying' 83
    # This does not download a model or make a cloud request.
    $checkArguments = '-c "import pymupdf, torch, sentence_transformers, bert_score, keyring; print(1)"'
    $check = Start-Process -FilePath $python -ArgumentList $checkArguments -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'runtime-check.log') -RedirectStandardError (Join-Path $root 'runtime-error.log')
    if ($check.ExitCode -ne 0) { throw 'Bundled runtime verification failed. See runtime-error.log.' }
    $markerData = @{version=$metadata.version; backend_sha256=$metadata.backend_sha256; runtime_sha256=$metadata.runtime_sha256;
      executable=(Join-Path $runtimePath 'pythonw.exe'); launcher=(Join-Path $backend 'launcher.py')} | ConvertTo-Json
    [IO.File]::WriteAllText($markerPath, $markerData, (New-Object Text.UTF8Encoding($false)))
    if ($PrepareOnly) { Write-State 'ready' 100; exit 0 }
    Write-State 'starting' 90
    $env:ZQS_PORT = "$Port"
    $launchArguments = '"' + (Join-Path $backend 'launcher.py') + '" --supervise'
    Start-Process -FilePath (Join-Path $runtimePath 'pythonw.exe') -ArgumentList $launchArguments -WorkingDirectory $backend -WindowStyle Hidden
    for ($attempt=0; $attempt -lt 120; $attempt++) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.ok -and $health.service -eq 'zitatlotse' -and $health.version -eq $metadata.version) {
                Write-State 'ready' 100
                exit 0
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw 'The service did not become ready. See backend\data\service.log.'
} catch {
    if ($lock) { Write-State 'failed' 0 $_.Exception.Message }
    throw
} finally {
    if ($package) { $package.Dispose() }
    if ($lock) { $lock.Dispose() }
}
