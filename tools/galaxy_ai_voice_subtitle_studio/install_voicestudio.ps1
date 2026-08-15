param(
    [string]$SnapshotRoot = "",
    [string]$RuntimeRoot = "",
    [string]$Python = "",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$toolRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
if (-not $SnapshotRoot) {
    $SnapshotRoot = Join-Path $toolRoot "vendor\voicestudio"
}
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models\VoiceStudio"
}
$SnapshotRoot = [System.IO.Path]::GetFullPath($SnapshotRoot)
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)

$snapshotMetadataPath = Join-Path $SnapshotRoot "SNAPSHOT.json"
if (-not (Test-Path -LiteralPath $snapshotMetadataPath -PathType Leaf)) {
    throw "VoiceStudio snapshot metadata was not found: $snapshotMetadataPath"
}
$snapshot = Get-Content -LiteralPath $snapshotMetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$snapshot.version
if (-not $version) {
    throw "VoiceStudio snapshot version is empty."
}

$runtimeSource = Join-Path $RuntimeRoot ("sources\" + $version)
$venvRoot = Join-Path $RuntimeRoot ".venv"
$runtimePython = Join-Path $venvRoot "Scripts\python.exe"
$installerVenv = Join-Path $RuntimeRoot ".installer"
$installerPython = Join-Path $installerVenv "Scripts\python.exe"
$webviewSite = Join-Path $RuntimeRoot "webview\site-packages"
$webviewWheel = Join-Path $toolRoot "vendor\wheels\tkwry-0.1.4-cp310-abi3-win_amd64.whl"
$metadataPath = Join-Path $RuntimeRoot "runtime.json"

function Invoke-Checked {
    param(
        [string]$Description,
        [scriptblock]$Command
    )
    Write-Host $Description -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Resolve-PythonRuntime {
    if ($Python) {
        $candidate = [System.IO.Path]::GetFullPath($Python)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Python executable was not found: $candidate"
        }
        return $candidate
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($versionId in @("3.11", "3.12", "3.13")) {
            $candidate = & $launcher.Source ("-" + $versionId) -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                return ([string]$candidate).Trim()
            }
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $pythonCommand.Source
        }
    }
    throw "Python 3.11, 3.12, or 3.13 was not found."
}

Write-Host "Installing the Galaxy-managed VoiceStudio $version runtime..." -ForegroundColor Green
$hostPython = Resolve-PythonRuntime
Write-Host "Host Python: $hostPython"

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeSource -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $RuntimeRoot "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $RuntimeRoot "cache") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $RuntimeRoot "logs") -Force | Out-Null
New-Item -ItemType Directory -Path $webviewSite -Force | Out-Null
Remove-Item -LiteralPath $metadataPath -Force -ErrorAction SilentlyContinue

Write-Host "Copying the immutable VoiceStudio snapshot..." -ForegroundColor Cyan
& robocopy $SnapshotRoot $runtimeSource /E /XD node_modules __pycache__ .venv target /XF *.pyc *.pyo | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Copying the VoiceStudio snapshot failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $webviewWheel -PathType Leaf)) {
    throw "The bundled WebView wheel was not found: $webviewWheel"
}
Invoke-Checked "Installing the embedded WebView bridge" {
    & $hostPython -m pip install --disable-pip-version-check --no-index --no-deps --upgrade --target $webviewSite $webviewWheel
}

if (-not (Test-Path -LiteralPath $installerPython -PathType Leaf)) {
    Invoke-Checked "Creating the installer environment" {
        & $hostPython -m venv $installerVenv
    }
}
Invoke-Checked "Installing the pinned uv package manager" {
    & $installerPython -m pip install --disable-pip-version-check --upgrade "uv==0.12.5"
}

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    Invoke-Checked "Creating the VoiceStudio Python environment" {
        & $installerPython -m uv venv --python $hostPython $venvRoot
    }
}

$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$env:UV_PROJECT_ENVIRONMENT = $venvRoot
try {
    Push-Location $runtimeSource
    try {
        Invoke-Checked "Installing VoiceStudio dependencies from the frozen lockfile" {
            & $installerPython -m uv sync --frozen --no-dev --python $runtimePython
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($null -eq $previousEnvironment) {
        Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    }
    else {
        $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    }
}

Invoke-Checked "Validating the VoiceStudio backend" {
    & $runtimePython -c "import fastapi, uvicorn, torch, omnivoice; print('VoiceStudio backend ready'); print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available())"
}

$metadata = @{
    schema_version = 1
    snapshot_version = $version
    source = $runtimeSource
    python = $runtimePython
    installed_at = [DateTimeOffset]::UtcNow.ToString("o")
} | ConvertTo-Json
[System.IO.File]::WriteAllText(
    $metadataPath,
    $metadata,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host ""
Write-Host "VoiceStudio local runtime is ready at $RuntimeRoot" -ForegroundColor Green
Write-Host "Models are downloaded only when selected inside VoiceStudio."
if (-not $NonInteractive) {
    Read-Host "Press Enter to close"
}
