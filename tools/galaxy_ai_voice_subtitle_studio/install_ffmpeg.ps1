$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$binDir = Join-Path $projectDir "bin"
$ffmpegExe = Join-Path $binDir "ffmpeg.exe"
$ffprobeExe = Join-Path $binDir "ffprobe.exe"
$sourceUrls = @(
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("galaxy-ffmpeg-" + [System.Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "ffmpeg.zip"
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

if ((Test-Path -LiteralPath $ffmpegExe) -and (Test-Path -LiteralPath $ffprobeExe)) {
    Write-Host "Bundled ffmpeg already exists:"
    Write-Host "  $ffmpegExe"
    Write-Host "  $ffprobeExe"
    exit 0
}

New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $sourceUrl = $null
    $downloaded = $false
    foreach ($candidateUrl in $sourceUrls) {
        Write-Host "Downloading ffmpeg..."
        Write-Host "  $candidateUrl"
        try {
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe -L --fail --retry 3 --connect-timeout 30 -o $zipPath $candidateUrl
                if ($LASTEXITCODE -ne 0) {
                    throw "curl failed with exit code $LASTEXITCODE"
                }
            }
            else {
                Invoke-WebRequest -Uri $candidateUrl -OutFile $zipPath
            }
            $sourceUrl = $candidateUrl
            $downloaded = $true
            break
        }
        catch {
            Write-Warning "Download failed: $($_.Exception.Message)"
            if (Test-Path -LiteralPath $zipPath) {
                Remove-Item -LiteralPath $zipPath -Force
            }
        }
    }

    if (-not $downloaded) {
        throw "Could not download ffmpeg from any configured source."
    }

    Write-Host "Extracting archive..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $downloadedFfmpeg = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    $downloadedFfprobe = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1

    if (-not $downloadedFfmpeg) {
        throw "Could not find ffmpeg.exe in downloaded archive."
    }

    Copy-Item -LiteralPath $downloadedFfmpeg.FullName -Destination $ffmpegExe -Force
    if ($downloadedFfprobe) {
        Copy-Item -LiteralPath $downloadedFfprobe.FullName -Destination $ffprobeExe -Force
    }

    @"
Bundled FFmpeg
===============

Source: $sourceUrl
Downloaded by: install_ffmpeg.ps1

FFmpeg is a third-party project. Review its license before redistribution:
https://ffmpeg.org/legal.html

This tool uses ffmpeg.exe for local video/audio conversion only.
"@ | Set-Content -LiteralPath (Join-Path $binDir "FFMPEG_SOURCE.txt") -Encoding UTF8

    Write-Host "Installed bundled ffmpeg:"
    Write-Host "  $ffmpegExe"
    if (Test-Path -LiteralPath $ffprobeExe) {
        Write-Host "  $ffprobeExe"
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
