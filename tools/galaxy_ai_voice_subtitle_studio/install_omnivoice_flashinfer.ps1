param(
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$runtimeRoot = Join-Path $env:LOCALAPPDATA "GalaxyAIStudio\models\OmniVoice"
$runtimePython = Join-Path $runtimeRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $runtimePython)) {
    throw "OmniVoice runtime is not installed: $runtimePython"
}

& $runtimePython -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "FlashInfer requires an NVIDIA CUDA OmniVoice runtime."
}

$cudaVersion = (& $runtimePython -c "import torch; print((torch.version.cuda or '').replace('.', ''))").Trim()
if (-not $cudaVersion) {
    throw "Could not detect the CUDA version used by PyTorch."
}
$indexUrl = "https://flashinfer.ai/whl/cu$cudaVersion/"

& $runtimePython -m pip install --upgrade `
    "flashinfer-python==0.6.15.post1" `
    "flashinfer-jit-cache==0.6.15.post1+cu$cudaVersion" `
    --extra-index-url $indexUrl
if ($LASTEXITCODE -ne 0) {
    throw "FlashInfer installation failed with exit code $LASTEXITCODE."
}

& $runtimePython -c "import flashinfer; from omnivoice.models.omnivoice_flashinfer import apply_flashinfer; print('FlashInfer runtime ready')"
if ($LASTEXITCODE -ne 0) {
    throw "FlashInfer validation failed."
}

Write-Host "FlashInfer installation completed." -ForegroundColor Green
if (-not $NonInteractive) {
    Read-Host "Press Enter to close"
}
