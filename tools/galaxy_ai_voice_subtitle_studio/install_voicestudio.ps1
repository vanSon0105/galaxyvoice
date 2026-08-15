param(
    [switch]$Quiet,
    [switch]$KeepInstaller
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$releaseApi = "https://api.github.com/repos/debpalash/VoiceStudio/releases/latest"
$downloadRoot = Join-Path $env:TEMP "GalaxyAIStudio\VoiceStudio"

function Get-LatestMsiAsset {
    $headers = @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "GalaxyAIStudio-VoiceStudio-Installer"
    }
    $release = Invoke-RestMethod -Uri $releaseApi -Headers $headers
    $assets = @($release.assets | Where-Object { $_.name -match "(?i)\.msi$" })
    if ($assets.Count -eq 0) {
        throw "The latest VoiceStudio release does not contain a Windows MSI."
    }
    $preferred = @($assets | Where-Object { $_.name -match "(?i)(x64|x86_64)" })
    if ($preferred.Count -gt 0) {
        return $preferred[0]
    }
    return $assets[0]
}

New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
$asset = Get-LatestMsiAsset
$installerPath = Join-Path $downloadRoot $asset.name

Write-Host "Downloading VoiceStudio $($asset.name)..."
Invoke-WebRequest `
    -Uri $asset.browser_download_url `
    -Headers @{ "User-Agent" = "GalaxyAIStudio-VoiceStudio-Installer" } `
    -UseBasicParsing `
    -OutFile $installerPath

if ($asset.digest -and $asset.digest -match "^sha256:(?<hash>[0-9a-fA-F]{64})$") {
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
    if ($actualHash -ne $Matches.hash) {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
        throw "VoiceStudio MSI checksum verification failed."
    }
}

$arguments = @("/i", "`"$installerPath`"", "/norestart")
if ($Quiet) {
    $arguments += "/quiet"
}

Write-Host "Starting the official VoiceStudio MSI..."
$process = Start-Process -FilePath "msiexec.exe" -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -notin @(0, 3010)) {
    throw "VoiceStudio installer failed with exit code $($process.ExitCode)."
}

if (-not $KeepInstaller) {
    Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
}

Write-Host "VoiceStudio installation completed." -ForegroundColor Green
if (-not $Quiet) {
    Read-Host "Press Enter to close"
}
