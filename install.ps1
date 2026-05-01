<#
.SYNOPSIS
  Pharos installer for Windows (PowerShell 5.1+ / 7+).

.DESCRIPTION
  Three modes:
    -Docker    Build & start the Docker stack. No Python/Node required locally.
    -Native    Install backend (Python venv) + frontend (npm) for development.
    -Quick     Auto-config + Docker stack with minimal prompts.

.PARAMETER Dev
  Install Python [dev] extras (pytest, ruff, mypy).

.PARAMETER SkipFrontend
  In native mode, skip 'npm install'.

.PARAMETER NoPrompt
  Non-interactive (Docker mode); fail if .env not yet set.

.EXAMPLE
  .\install.ps1 -Quick
  .\install.ps1 -Docker
  .\install.ps1 -Native -Dev
#>
[CmdletBinding(DefaultParameterSetName = 'Interactive')]
param(
    [Parameter(ParameterSetName = 'Docker')] [switch]$Docker,
    [Parameter(ParameterSetName = 'Native')] [switch]$Native,
    [Parameter(ParameterSetName = 'Quick')]  [switch]$Quick,
    [switch]$Dev,
    [switch]$SkipFrontend,
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Err([string]$msg)  { Write-Host "error: $msg" -ForegroundColor Red }

@'

   ____  _
  |  _ \| |__   __ _ _ __ ___  ___
  | |_) | '_ \ / _` | '__/ _ \/ __|
  |  __/| | | | (_| | | | (_) \__ \
  |_|   |_| |_|\__,_|_|  \___/|___/
                              v0.2

  A beam through the noise.

'@ | Write-Host

$mode = $null
if ($Docker) { $mode = 'docker' }
elseif ($Native) { $mode = 'native' }
elseif ($Quick) { $mode = 'quick' }

if (-not $mode) {
    Write-Host "How would you like to install Pharos?"
    Write-Host "  1) Docker  (recommended; one container)"
    Write-Host "  2) Native  (Python venv + npm; for hacking on the code)"
    Write-Host "  3) Quick   (Docker, auto-config; minimal prompts)"
    $choice = Read-Host "Choose 1/2/3 [1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = '1' }
    switch ($choice) {
        '1' { $mode = 'docker' }
        '2' { $mode = 'native' }
        '3' { $mode = 'quick' }
        default { Err "Invalid choice"; exit 1 }
    }
}

function Write-Env {
    Step "Configuring .env"
    $args = @()
    if ($NoPrompt -or $mode -eq 'quick') { $args += '-NoPrompt' }
    & "$root\setup-env.ps1" @args
}

function Install-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Err "Docker is required. Install Docker Desktop and try again."; exit 1
    }
    try { docker compose version | Out-Null }
    catch { Err "Docker Compose v2 is required (docker compose). Update Docker."; exit 1 }

    Write-Env

    Step "Building and starting the Docker stack"
    docker compose -f deploy/compose/docker-compose.aio.yml up -d --build
    Ok "Stack is up"

    Write-Host ""
    Write-Host "Bootstrapping admin user…"
    if ($NoPrompt -or $mode -eq 'quick') {
        $bytes = New-Object byte[] 16
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $pw = [Convert]::ToBase64String($bytes).Replace('+','').Replace('/','').Replace('=','').Substring(0,16)
        docker compose -f deploy/compose/docker-compose.aio.yml exec -T `
            -e "ADMIN_PW=$pw" pharos python /code/scripts/bootstrap_admin.py
        Write-Host ""
        Write-Host "Admin account created." -ForegroundColor Green
        Write-Host "  username: admin"
        Write-Host "  password: $pw"
        Write-Host ""
        Write-Host "Save this password -- it will not be shown again."
    } else {
        try {
            docker compose -f deploy/compose/docker-compose.aio.yml exec pharos pharos adduser admin --admin
        } catch { Warn "(admin may already exist)" }
    }

    Write-Host ""
    Write-Host "Pharos is running." -ForegroundColor Green
    Write-Host "  Frontend : http://localhost:3000"
    Write-Host "  API      : http://localhost:8000/docs"
    Write-Host ""
    Write-Host "Tail the logs:   docker compose -f deploy/compose/docker-compose.aio.yml logs -f"
    Write-Host "Stop the stack:  docker compose -f deploy/compose/docker-compose.aio.yml down"
}

function Install-Native {
    Step "Checking Python"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Err "Python 3.11+ is required (python.exe not found)."; exit 1
    }
    $ver = & python -c 'import sys; print("%d.%d" % sys.version_info[:2])'
    Ok "Found python $ver"
    if ($ver -notmatch '^3\.(11|12|13|14)') {
        Warn "Pharos targets Python 3.11+; $ver may not be supported."
    }

    if (-not (Test-Path .venv)) {
        Step "Creating virtual environment at .venv"
        python -m venv .venv
    } else {
        Step "Reusing existing .venv"
    }
    & .\.venv\Scripts\Activate.ps1

    Step "Installing Pharos backend"
    pip install --upgrade pip wheel | Out-Null
    if ($Dev) {
        pip install -e './backend[dev]'
    } else {
        pip install -e ./backend
    }
    Ok "Backend installed"

    Write-Env

    Step "Initializing SQLite databases"
    pharos init

    if (-not $NoPrompt) {
        Write-Host ""
        $yn = Read-Host "Create an admin user now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($yn) -or $yn -match '^[Yy]') {
            $u = Read-Host "Username [admin]"
            if ([string]::IsNullOrWhiteSpace($u)) { $u = 'admin' }
            try { pharos adduser $u --admin } catch { Warn "User creation failed." }
        }
    }

    if (-not $SkipFrontend) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            Warn "npm not found - skipping frontend install. Install Node 20+ to develop the UI."
        } else {
            Step "Installing frontend dependencies"
            Push-Location frontend
            try { npm install } finally { Pop-Location }
            Ok "Frontend dependencies installed"
        }
    }

    Write-Host ""
    Write-Host "Pharos (native) is ready." -ForegroundColor Green
    Write-Host ""
    Write-Host "To run it locally (in separate terminals):"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pharos sweep                   # ingestion"
    Write-Host "  pharos light                   # LLM enrichment"
    Write-Host "  pharos notify                  # in-app notifications"
    Write-Host "  uvicorn pharos.api.app:create_app --factory --reload --port 8000"
    Write-Host "  cd frontend && npm run dev     # open http://localhost:3000"
}

switch ($mode) {
    'docker' { Install-Docker }
    'quick'  { Install-Docker }
    'native' { Install-Native }
    default  { Err "Unknown mode: $mode"; exit 1 }
}
