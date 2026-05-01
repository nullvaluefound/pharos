<#
  Pharos one-liner installer for Windows.

  iwr -useb https://raw.githubusercontent.com/nullvaluefound/pharos/main/scripts/quickstart.ps1 | iex
#>
$ErrorActionPreference = 'Stop'

$repo = if ($env:PHAROS_REPO) { $env:PHAROS_REPO } else { 'https://github.com/nullvaluefound/pharos.git' }
$dir  = if ($env:PHAROS_DIR)  { $env:PHAROS_DIR }  else { Join-Path $env:USERPROFILE 'pharos' }

if (Test-Path $dir) {
    Write-Host "==> Reusing existing checkout at $dir" -ForegroundColor Cyan
    Push-Location $dir
    try { git pull --ff-only } catch { }
    Pop-Location
} else {
    Write-Host "==> Cloning $repo -> $dir" -ForegroundColor Cyan
    git clone $repo $dir
}

Set-Location $dir
& .\install.ps1 -Quick
