param(
    [ValidateSet("auto", "cuda", "xpu", "cpu")]
    [string]$Device = "auto",
    [switch]$DownloadModel,
    [string]$Model = "k2-fsa/OmniVoice"
)

$ErrorActionPreference = "Stop"
$runtimeRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models\OmniVoice"
$venvRoot = Join-Path $runtimeRoot ".venv"
$runtimePython = Join-Path $venvRoot "Scripts\python.exe"
$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\omnivoice"))

function Find-PythonRuntime {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("3.12", "3.11", "3.10", "3.13")) {
            & $launcher.Source "-$version" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @($launcher.Source, "-$version")
            }
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @($python.Source)
        }
    }
    throw "Python 3.10 or newer was not found. Install Python 3.11 or 3.12 and retry."
}

function Invoke-Checked {
    param(
        [string]$Description,
        [scriptblock]$Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path (Join-Path $sourceRoot "pyproject.toml"))) {
    throw "OmniVoice source was not found at $sourceRoot"
}

if ($Device -eq "auto") {
    $Device = if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) { "cuda" } else { "cpu" }
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "checkpoints") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "voices") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "cache") -Force | Out-Null

if (-not (Test-Path $runtimePython)) {
    $pythonCommand = Find-PythonRuntime
    $pythonExe = $pythonCommand[0]
    $pythonArgs = @()
    if ($pythonCommand.Count -gt 1) {
        $pythonArgs += $pythonCommand[1..($pythonCommand.Count - 1)]
    }
    Invoke-Checked "Creating OmniVoice virtual environment" {
        & $pythonExe @pythonArgs -m venv $venvRoot
    }
}

Invoke-Checked "Updating Python packaging tools" {
    & $runtimePython -m pip install --upgrade pip setuptools wheel
}

if ($Device -eq "cuda") {
    Invoke-Checked "Installing CUDA PyTorch" {
        & $runtimePython -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
    }
}
elseif ($Device -eq "xpu") {
    Invoke-Checked "Installing Intel XPU PyTorch" {
        & $runtimePython -m pip install torch torchaudio --index-url https://pytorch-extension.intel.com/release-whl/stable/xpu/us/
    }
}
else {
    Invoke-Checked "Installing CPU PyTorch" {
        & $runtimePython -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
    }
}

Invoke-Checked "Installing OmniVoice" {
    & $runtimePython -m pip install $sourceRoot
}
Invoke-Checked "Installing multilingual text normalization" {
    & $runtimePython -m pip install num2words
}
& $runtimePython -m pip install WeTextProcessing
if ($LASTEXITCODE -ne 0) {
    Write-Warning "WeTextProcessing could not be installed. English/Chinese text normalization will be unavailable."
}

$metadata = @{
    version = 1
    device = $Device
    source = $sourceRoot
    installed_at = [DateTimeOffset]::UtcNow.ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $runtimeRoot "runtime.json") -Value $metadata -Encoding UTF8

if ($DownloadModel) {
    $env:HF_HOME = Join-Path $runtimeRoot "cache\huggingface"
    $env:GALAXY_OMNIVOICE_MODEL = $Model
    Invoke-Checked "Downloading OmniVoice model" {
        & $runtimePython -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['GALAXY_OMNIVOICE_MODEL'])"
    }
    Remove-Item Env:GALAXY_OMNIVOICE_MODEL -ErrorAction SilentlyContinue
}

Invoke-Checked "Validating OmniVoice runtime" {
    & $runtimePython -c "import torch, omnivoice; print('OmniVoice runtime ready'); print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available()); print('xpu:', bool(hasattr(torch, 'xpu') and torch.xpu.is_available()))"
}
Write-Host ""
Write-Host "OmniVoice installation completed at $runtimeRoot" -ForegroundColor Green
Read-Host "Press Enter to close"
