$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$binDir = Join-Path $projectDir "bin"
$ffmpegExe = Join-Path $binDir "ffmpeg.exe"
$ffprobeExe = Join-Path $binDir "ffprobe.exe"
$ffplayExe = Join-Path $binDir "ffplay.exe"
$sourcePackages = @(
    @{
        Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        ChecksumUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256"
        ArchiveName = "ffmpeg-master-latest-win64-gpl.zip"
    },
    @{
        Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        ChecksumUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256"
        ArchiveName = "ffmpeg-release-essentials.zip"
    }
)
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("galaxy-ffmpeg-" + [System.Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "ffmpeg.zip"
$checksumPath = Join-Path $tempRoot "ffmpeg.sha256"
$extractDir = Join-Path $tempRoot "extract"

function Download-File {
    param([string]$Url, [string]$Destination)
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 --connect-timeout 30 -o $Destination $Url
        if ($LASTEXITCODE -ne 0) {
            throw "curl failed with exit code $LASTEXITCODE"
        }
    }
    else {
        Invoke-WebRequest -Uri $Url -OutFile $Destination
    }
}

function Assert-ArchiveChecksum {
    param([string]$ArchivePath, [string]$ManifestPath, [string]$ArchiveName)
    $escapedName = [Regex]::Escape($ArchiveName)
    $expected = $null
    foreach ($line in Get-Content -LiteralPath $ManifestPath) {
        if ($line -match ("^([A-Fa-f0-9]{64})\s+\*?" + $escapedName + "\s*$")) {
            $expected = $Matches[1]
            break
        }
        if (-not $expected -and $line -match "^([A-Fa-f0-9]{64})\s*$") {
            $expected = $Matches[1]
        }
    }
    if (-not $expected) {
        throw "Checksum manifest does not contain SHA-256 for $ArchiveName."
    }
    $actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if ($actual -ne $expected) {
        throw "FFmpeg archive checksum mismatch. Expected $expected, received $actual."
    }
    Write-Host "SHA-256 verified: $actual"
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

if ((Test-Path -LiteralPath $ffmpegExe) -and (Test-Path -LiteralPath $ffprobeExe) -and (Test-Path -LiteralPath $ffplayExe)) {
    Write-Host "Bundled FFmpeg tools already exist:"
    Write-Host "  $ffmpegExe"
    Write-Host "  $ffprobeExe"
    Write-Host "  $ffplayExe"
    exit 0
}

New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $sourceUrl = $null
    $downloadedFfmpeg = $null
    $downloadedFfprobe = $null
    $downloadedFfplay = $null
    foreach ($candidate in $sourcePackages) {
        $candidateUrl = $candidate.Url
        Write-Host "Downloading ffmpeg..."
        Write-Host "  $candidateUrl"
        try {
            if (Test-Path -LiteralPath $zipPath) {
                Remove-Item -LiteralPath $zipPath -Force
            }
            if (Test-Path -LiteralPath $extractDir) {
                Remove-Item -LiteralPath $extractDir -Recurse -Force
            }
            if (Test-Path -LiteralPath $checksumPath) {
                Remove-Item -LiteralPath $checksumPath -Force
            }
            Download-File -Url $candidateUrl -Destination $zipPath
            Download-File -Url $candidate.ChecksumUrl -Destination $checksumPath
            Assert-ArchiveChecksum -ArchivePath $zipPath -ManifestPath $checksumPath -ArchiveName $candidate.ArchiveName
            Write-Host "Extracting archive..."
            Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

            $downloadedFfmpeg = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
            $downloadedFfprobe = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
            $downloadedFfplay = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffplay.exe" | Select-Object -First 1
            if (-not $downloadedFfmpeg -or -not $downloadedFfprobe -or -not $downloadedFfplay) {
                throw "Downloaded archive does not contain ffmpeg.exe, ffprobe.exe, and ffplay.exe."
            }

            $sourceUrl = $candidateUrl
            break
        }
        catch {
            Write-Warning "Download failed: $($_.Exception.Message)"
            if (Test-Path -LiteralPath $zipPath) {
                Remove-Item -LiteralPath $zipPath -Force
            }
        }
    }

    if (-not $sourceUrl) {
        throw "Could not download a complete FFmpeg toolset from any configured source."
    }

    Copy-Item -LiteralPath $downloadedFfmpeg.FullName -Destination $ffmpegExe -Force
    Copy-Item -LiteralPath $downloadedFfprobe.FullName -Destination $ffprobeExe -Force
    Copy-Item -LiteralPath $downloadedFfplay.FullName -Destination $ffplayExe -Force

    @"
Bundled FFmpeg
===============

Source: $sourceUrl
Downloaded by: install_ffmpeg.ps1

FFmpeg is a third-party project. Review its license before redistribution:
https://ffmpeg.org/legal.html

This tool uses ffmpeg.exe/ffprobe.exe for local media processing and ffplay.exe for in-app preview audio.
"@ | Set-Content -LiteralPath (Join-Path $binDir "FFMPEG_SOURCE.txt") -Encoding UTF8

    Write-Host "Installed bundled ffmpeg:"
    Write-Host "  $ffmpegExe"
    Write-Host "  $ffprobeExe"
    Write-Host "  $ffplayExe"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
