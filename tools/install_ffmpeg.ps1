# install_ffmpeg.ps1 — Unduh & pasang ffmpeg.exe untuk build Windows.
# Dipanggil dari build_windows.bat. Semua error jadi terminating (exit code != 0).
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$DestExe
)

$ErrorActionPreference = "Stop"

$destDir = Split-Path -Parent $DestExe
if (-not (Test-Path -LiteralPath $destDir)) {
    New-Item -ItemType Directory -Path $destDir | Out-Null
}

$zipPath = Join-Path $env:TEMP "ave_ffmpeg_dl.zip"
$tmpDir = Join-Path $env:TEMP "ave_ffmpeg_tmp"

Write-Host "Mengunduh ffmpeg dari $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $zipPath -UserAgent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
$size = (Get-Item -LiteralPath $zipPath).Length
Write-Host "Ukuran unduhan: $size byte"
if ($size -lt 50000000) {
    throw "File unduhan hanya $size byte (harusnya 100MB+). Kemungkinan halaman error, bukan zip."
}

Write-Host "Mengekstrak arsip ..."
if (Test-Path -LiteralPath $tmpDir) { Remove-Item -LiteralPath $tmpDir -Recurse -Force }
Expand-Archive -LiteralPath $zipPath -DestinationPath $tmpDir -Force

Write-Host "Mencari ffmpeg.exe dan ffprobe.exe di hasil ekstrak ..."
$ffmpeg = Get-ChildItem -LiteralPath $tmpDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
$ffprobe = Get-ChildItem -LiteralPath $tmpDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
if (-not $ffmpeg) {
    $listing = Get-ChildItem -LiteralPath $tmpDir -Recurse | Select-Object -First 20 | ForEach-Object { $_.FullName }
    Write-Host "Isi arsip (20 pertama):"
    $listing | ForEach-Object { Write-Host "  $_" }
    throw "ffmpeg.exe tidak ditemukan di dalam arsip."
}

Write-Host "Menyalin $($ffmpeg.FullName) ke $DestExe ..."
Copy-Item -LiteralPath $ffmpeg.FullName -Destination $DestExe -Force
if ($ffprobe) {
    $destProbe = Join-Path (Split-Path -Parent $DestExe) "ffprobe.exe"
    Write-Host "Menyalin $($ffprobe.FullName) ke $destProbe ..."
    Copy-Item -LiteralPath $ffprobe.FullName -Destination $destProbe -Force
} else {
    Write-Host "PERINGATAN: ffprobe.exe tidak ada di arsip, lewati."
}

Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "ffmpeg.exe siap."
