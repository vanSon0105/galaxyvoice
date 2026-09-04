$ErrorActionPreference = "Stop"
$rapidOcrVersion = "3.9.2"
$installerMutex = [System.Threading.Mutex]::new($false, "Local\GalaxyAIStudio-VideoOCR-Install")
try {
    $mutexAcquired = $installerMutex.WaitOne(0)
}
catch [System.Threading.AbandonedMutexException] {
    $mutexAcquired = $true
}
if (-not $mutexAcquired) {
    $installerMutex.Dispose()
    throw "Another video OCR installation is already running."
}

try {
    $runtimeRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models\VideoOCR"
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
        if (Test-Path -LiteralPath $knownPython) { return $knownPython }
        return $null
    }

    function Install-Python312 {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python 3.12 is required. Install it, then run this installer again."
        }
        Write-Host "Installing Python 3.12 for the isolated video OCR runtime..."
        & $winget.Source install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "winget could not install Python 3.12 (exit code $LASTEXITCODE)." }
    }

    $python = Find-Python312
    if (-not $python) {
        Install-Python312
        $python = Find-Python312
    }
    if (-not $python) { throw "Python 3.12 was installed but could not be located." }

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creating isolated video OCR environment..."
        & $python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Could not create the video OCR environment." }
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw "Could not update pip in the video OCR environment." }
    Write-Host "Installing RapidOCR $rapidOcrVersion and ONNX Runtime..."
    & $venvPython -m pip install --upgrade "rapidocr==$rapidOcrVersion" "onnxruntime>=1.20,<2"
    if ($LASTEXITCODE -ne 0) { throw "Could not install the video OCR packages." }
    & $venvPython -c "import cv2, numpy, onnxruntime, rapidocr; print('video OCR runtime ready')"
    if ($LASTEXITCODE -ne 0) { throw "Video OCR runtime verification failed." }

    Write-Host ""
    Write-Host "Video OCR is ready:"
    Write-Host "  $venvPython"
}
finally {
    if ($mutexAcquired) { $installerMutex.ReleaseMutex() }
    $installerMutex.Dispose()
}
