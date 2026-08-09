param(
    [ValidateSet("auto", "cpu", "directml", "cuda")]
    [string]$Device = "auto"
)

$ErrorActionPreference = "Stop"
$runtimeVersion = "0.44.5"
$installerMutex = [System.Threading.Mutex]::new($false, "Local\GalaxyAIStudio-AudioSeparator-Install")
try {
    $mutexAcquired = $installerMutex.WaitOne(0)
}
catch [System.Threading.AbandonedMutexException] {
    $mutexAcquired = $true
}
if (-not $mutexAcquired) {
    $installerMutex.Dispose()
    throw "Another audio separator installation is already running."
}

try {
    $runtimeRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models\AudioSeparator"
    $venvDir = Join-Path $runtimeRoot ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    function Find-Python312 {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            $previousPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = "SilentlyContinue"
                $path = & $launcher.Source "-3.12" -c "import sys; print(sys.executable)" 2>$null
                $probeExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $previousPreference
            }
            if ($probeExitCode -eq 0 -and $path) {
                return ([string]$path).Trim()
            }
        }

        $knownPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path -LiteralPath $knownPython) {
            return $knownPython
        }
        return $null
    }

    function Install-Python312 {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python 3.12 is required. Install it, then run this installer again."
        }
        Write-Host "Installing Python 3.12 for the isolated audio separator runtime..."
        & $winget.Source install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "winget could not install Python 3.12 (exit code $LASTEXITCODE)."
        }
    }

    $python = Find-Python312
    if (-not $python) {
        Install-Python312
        $python = Find-Python312
    }
    if (-not $python) {
        throw "Python 3.12 was installed but could not be located. Open a new terminal and try again."
    }

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creating isolated audio separator environment..."
        & $python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the audio separator environment."
        }
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "Could not update pip in the audio separator environment."
    }

    $hasNvidia = $null -ne (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)
    $resolvedDevice = $Device
    if ($resolvedDevice -eq "auto") {
        $resolvedDevice = if ($hasNvidia) { "cuda" } else { "directml" }
    }
    if ($resolvedDevice -eq "cuda" -and -not $hasNvidia) {
        throw "NVIDIA CUDA was selected but no NVIDIA GPU was detected."
    }

    $extra = switch ($resolvedDevice) {
        "cuda" { "gpu" }
        "directml" { "dml" }
        default { "cpu" }
    }
    Write-Host "Installing audio-separator $runtimeVersion for $($resolvedDevice.ToUpper())..."
    & $venvPython -m pip install --upgrade "audio-separator[$extra]==$runtimeVersion"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install audio-separator for $resolvedDevice."
    }

    & $venvPython -c "import audio_separator; from audio_separator.separator import Separator; print('audio-separator runtime ready')"
    if ($LASTEXITCODE -ne 0) {
        throw "Audio separator verification failed."
    }

    Write-Host ""
    Write-Host "Audio separator is ready:"
    Write-Host "  $venvPython"
    Write-Host "Device profile: $resolvedDevice"
    Write-Host "Galaxy Studio will use model files from the local Ultimate Vocal Remover folder."
}
finally {
    if ($mutexAcquired) {
        $installerMutex.ReleaseMutex()
    }
    $installerMutex.Dispose()
}
