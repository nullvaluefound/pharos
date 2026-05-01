<#
.SYNOPSIS
  Pharos -- interactive .env bootstrap (Windows).

.DESCRIPTION
  Creates or updates .env with sensible values:
    - Prompts for OPENAI_API_KEY (Enter to skip; you can set it later).
    - Auto-generates a strong JWT_SECRET if it's still the placeholder.
    - Lets you override OPENAI_MODEL and PHAROS_DB_DIR.

  This script does not install anything; it only writes .env. Use it before
  `docker compose up` (or before running install.ps1, which calls this
  automatically).

.PARAMETER NoPrompt
  Generate JWT_SECRET only; leave everything else untouched. Useful for CI.

.EXAMPLE
  .\setup-env.ps1
  .\setup-env.ps1 -NoPrompt
#>

[CmdletBinding()]
param(
  [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn2($m){ Write-Host "    $m" -ForegroundColor Yellow }

if (-not (Test-Path .env)) {
  Say "Creating .env from .env.example"
  Copy-Item .env.example .env
  Ok "wrote .env"
} else {
  Say "Updating existing .env (placeholders will be replaced)"
}

function Get-EnvValue {
  param([string]$Key)
  $line = Get-Content .env | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
  if ($null -eq $line) { return "" }
  return ($line -split '=', 2)[1]
}

function Set-EnvValue {
  param([string]$Key, [string]$Value)
  $existing = Get-Content .env
  $found = $false
  $new = foreach ($line in $existing) {
    if ($line -match "^$([regex]::Escape($Key))=") {
      $found = $true
      "$Key=$Value"
    } else {
      $line
    }
  }
  if (-not $found) { $new += "$Key=$Value" }
  # Write with explicit LF line endings + UTF-8 (no BOM). CRLF in .env breaks
  # docker compose env_file parsing (a trailing \r leaks into variable values
  # and causes "OPENAI_API_KEY != placeholder" comparisons to misbehave inside
  # Linux containers).
  $text = ($new -join "`n") + "`n"
  [IO.File]::WriteAllText((Join-Path $Root '.env'), $text, [Text.UTF8Encoding]::new($false))
}

# ----- JWT_SECRET -------------------------------------------------------------
$jwt = Get-EnvValue "JWT_SECRET"
if (-not $jwt -or $jwt -like "*please-change*" -or $jwt -eq "dev-secret-change-me") {
  $bytes = New-Object byte[] 64
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
  Set-EnvValue "JWT_SECRET" $secret
  Ok "generated a new JWT_SECRET"
} else {
  Ok "JWT_SECRET already set"
}

# ----- OPENAI_API_KEY ---------------------------------------------------------
$key = Get-EnvValue "OPENAI_API_KEY"
if ($key -and $key -ne "sk-replace-me") {
  Ok "OPENAI_API_KEY already set"
} elseif ($NoPrompt) {
  Warn2 "OPENAI_API_KEY is still the placeholder; edit .env before starting the lantern."
} else {
  Write-Host ""
  $secure = Read-Host -AsSecureString "Enter your OPENAI_API_KEY (Enter to skip)"
  $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
  [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  if ($plain) {
    Set-EnvValue "OPENAI_API_KEY" $plain
    Ok "OPENAI_API_KEY saved"
  } else {
    Warn2 "Skipped. The lantern will fail until you set OPENAI_API_KEY in .env."
  }
}

# ----- OPENAI_MODEL -----------------------------------------------------------
if (-not $NoPrompt) {
  $model = Get-EnvValue "OPENAI_MODEL"
  if (-not $model) { $model = "gpt-4o-mini" }
  $newModel = Read-Host "OpenAI model [$model]"
  if ($newModel -and $newModel -ne $model) {
    Set-EnvValue "OPENAI_MODEL" $newModel
    Ok "OPENAI_MODEL set to $newModel"
  }
}

# ----- PHAROS_DB_DIR ----------------------------------------------------------
if (-not $NoPrompt) {
  $dir = Get-EnvValue "PHAROS_DB_DIR"
  if (-not $dir) { $dir = "./data" }
  $newDir = Read-Host "Pharos data directory [$dir]"
  if ($newDir -and $newDir -ne $dir) {
    Set-EnvValue "PHAROS_DB_DIR" $newDir
    Ok "PHAROS_DB_DIR set to $newDir"
  }
}

Write-Host ""
Ok ".env is ready. You can edit it any time."
