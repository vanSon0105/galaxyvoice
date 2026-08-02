param(
    [switch]$AcceptNonCommercialLicense,
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "auto"
)

$ErrorActionPreference = "Stop"

if (-not $AcceptNonCommercialLicense) {
    throw "ProPainter is licensed for non-commercial use only. Re-run with -AcceptNonCommercialLicense after reviewing https://github.com/sczhou/ProPainter/blob/main/LICENSE"
}

$installerMutex = [System.Threading.Mutex]::new($false, "Local\GalaxyAIStudio-ProPainter-Install")
try {
    $mutexAcquired = $installerMutex.WaitOne(0)
}
catch [System.Threading.AbandonedMutexException] {
    $mutexAcquired = $true
}
if (-not $mutexAcquired) {
    $installerMutex.Dispose()
    throw "Another ProPainter installation is already running. Finish or close it before trying again."
}

try {
$modelRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models"
$repoDir = Join-Path $modelRoot "ProPainter"
$venvDir = Join-Path $repoDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$repoUrl = "https://github.com/sczhou/ProPainter.git"
$repoCommit = "e870e79321c31b733e2031af5aa2fb1fe3ac7eec"

function Find-CompatiblePython {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("3.12", "3.11", "3.10")) {
            $previousPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = "SilentlyContinue"
                $path = & $launcher.Source "-$version" -c "import sys; print(sys.executable)" 2>$null
                $probeExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $previousPreference
            }
            if ($probeExitCode -eq 0 -and $path) {
                return ([string]$path).Trim()
            }
        }
    }

    $knownPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $knownPython) {
        return $knownPython
    }
    return $null
}

function Install-CompatiblePython {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.10-3.12 is required. Install Python 3.12, then run this installer again."
    }
    Write-Host "Installing Python 3.12 for the ProPainter environment..."
    & $winget.Source install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install Python 3.12 (exit code $LASTEXITCODE)."
    }
}

$python = Find-CompatiblePython
if (-not $python) {
    Install-CompatiblePython
    $python = Find-CompatiblePython
}
if (-not $python) {
    throw "Python 3.12 was installed but could not be located. Open a new terminal and run this installer again."
}

$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) {
    throw "Git is required to install ProPainter. Install Git for Windows and run this installer again."
}

if (
    (Test-Path -LiteralPath $repoDir) -and
    (
        -not (Test-Path -LiteralPath (Join-Path $repoDir "inference_propainter.py")) -or
        -not (Test-Path -LiteralPath (Join-Path $repoDir ".git"))
    )
) {
    $backupDir = "$repoDir.incomplete-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Host "Moving the incomplete ProPainter folder to: $backupDir"
    Move-Item -LiteralPath $repoDir -Destination $backupDir
}

if (-not (Test-Path -LiteralPath $repoDir)) {
    New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
    $stagingDir = "$repoDir.installing-$PID"
    try {
        Write-Host "Downloading the reviewed ProPainter revision..."
        & $git.Source clone --no-checkout --filter=blob:none $repoUrl $stagingDir
        if ($LASTEXITCODE -ne 0) {
            throw "Could not clone ProPainter (exit code $LASTEXITCODE)."
        }
        & $git.Source -C $stagingDir checkout --detach $repoCommit
        if ($LASTEXITCODE -ne 0) {
            throw "Could not check out the reviewed ProPainter revision $repoCommit."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $stagingDir "inference_propainter.py"))) {
            throw "The downloaded ProPainter revision is incomplete."
        }
        Move-Item -LiteralPath $stagingDir -Destination $repoDir
    }
    finally {
        if (Test-Path -LiteralPath $stagingDir) {
            [System.IO.Directory]::Delete($stagingDir, $true)
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $repoDir "inference_propainter.py"))) {
    throw "The ProPainter folder is incomplete: $repoDir"
}

$currentCommit = (& $git.Source -C $repoDir rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the installed ProPainter revision."
}
if ($currentCommit -ne $repoCommit) {
    Write-Host "Updating ProPainter to the reviewed revision..."
    & $git.Source -C $repoDir fetch --depth 1 origin $repoCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download the reviewed ProPainter revision $repoCommit."
    }
    & $git.Source -C $repoDir checkout --detach $repoCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Could not switch ProPainter to the reviewed revision $repoCommit."
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating an isolated Python environment..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the ProPainter Python environment."
    }
}

& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not update pip in the ProPainter environment."
}

$hasNvidia = $null -ne (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)
$resolvedDevice = $Device
if ($resolvedDevice -eq "auto") {
    $resolvedDevice = if ($hasNvidia) { "cuda" } else { "cpu" }
}
if ($resolvedDevice -eq "cuda" -and -not $hasNvidia) {
    throw "NVIDIA GPU was selected but nvidia-smi is unavailable. Choose Auto or CPU."
}

$torchIndex = if ($resolvedDevice -eq "cuda") {
    "https://download.pytorch.org/whl/cu124"
}
else {
    "https://download.pytorch.org/whl/cpu"
}

Write-Host "Installing PyTorch for $($resolvedDevice.ToUpper())..."
& $venvPython -m pip install --force-reinstall "torch==2.5.1" "torchvision==0.20.1" --index-url $torchIndex
if ($LASTEXITCODE -ne 0) {
    throw "Could not install PyTorch."
}

Write-Host "Installing ProPainter dependencies..."
& $venvPython -m pip install -r (Join-Path $repoDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install ProPainter dependencies."
}

$verification = "import torch, torchvision, cv2, imageio; available = torch.cuda.is_available() and torch.backends.cudnn.is_available(); print('PyTorch:', torch.__version__); print('CUDA/cuDNN available:', available)"
if ($resolvedDevice -eq "cuda") {
    $verification += "; assert available, 'The installed PyTorch runtime cannot use CUDA with cuDNN'"
}
& $venvPython -c $verification
if ($LASTEXITCODE -ne 0) {
    throw "ProPainter verification failed."
}

Write-Host ""
Write-Host "ProPainter is ready:"
Write-Host "  $repoDir"
Write-Host "Pretrained weights will download automatically on the first AI inpainting run."
Write-Host "License: non-commercial use only (NTU S-Lab License 1.0)."
}
finally {
    if ($mutexAcquired) {
        $installerMutex.ReleaseMutex()
    }
    $installerMutex.Dispose()
}
