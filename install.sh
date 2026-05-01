#!/usr/bin/env bash
# Pharos installer (Linux / macOS / WSL).
#
# Three modes, choose one (default is interactive):
#   --docker        Build & start the Docker stack. No Python/Node needed locally.
#   --native        Install backend (Python venv) and frontend (npm) for dev.
#   --quick         One-shot: configure .env (auto-secrets) + Docker stack.
#
# Common flags:
#   --dev               Install Python [dev] extras (pytest, ruff, mypy)
#   --skip-frontend     With --native, skip `npm install`
#   --no-prompt         Non-interactive (Docker mode); fail if .env not yet set
#
# Environment overrides (handy in CI):
#   OPENAI_API_KEY=sk-... ./install.sh --quick
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE=""
DEV=0
WITH_FRONTEND=1
NO_PROMPT=0
for arg in "$@"; do
  case "$arg" in
    --docker)         MODE=docker ;;
    --native)         MODE=native ;;
    --quick|-q)       MODE=quick ;;
    --dev|-d)         DEV=1 ;;
    --skip-frontend)  WITH_FRONTEND=0 ;;
    --no-prompt|-y)   NO_PROMPT=1 ;;
    -h|--help)
      sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

C_CYAN='\033[1;36m'; C_GREEN='\033[1;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[1;31m'; C_OFF='\033[0m'
step() { echo -e "${C_CYAN}==> $*${C_OFF}"; }
ok()   { echo -e "    ${C_GREEN}$*${C_OFF}"; }
warn() { echo -e "    ${C_YELLOW}$*${C_OFF}"; }
err()  { echo -e "${C_RED}error: $*${C_OFF}" >&2; }

print_banner() {
  cat <<'EOF'

   ____  _                          
  |  _ \| |__   __ _ _ __ ___  ___ 
  | |_) | '_ \ / _` | '__/ _ \/ __|
  |  __/| | | | (_| | | | (_) \__ \
  |_|   |_| |_|\__,_|_|  \___/|___/
                              v0.2

  A beam through the noise.

EOF
}
print_banner

# -----------------------------------------------------------------------------
# Pick mode interactively if not given
# -----------------------------------------------------------------------------
if [[ -z "$MODE" ]]; then
  echo "How would you like to install Pharos?"
  echo "  1) Docker (recommended; one container)"
  echo "  2) Native (Python venv + npm; for hacking on the code)"
  echo "  3) Quick (Docker, auto-config; minimal prompts)"
  read -r -p "Choose 1/2/3 [1]: " choice
  case "${choice:-1}" in
    1) MODE=docker ;;
    2) MODE=native ;;
    3) MODE=quick ;;
    *) err "Invalid choice"; exit 1 ;;
  esac
fi

# -----------------------------------------------------------------------------
# Common .env bootstrap
# -----------------------------------------------------------------------------
write_env() {
  step "Configuring .env"
  if [[ "$NO_PROMPT" -eq 1 || "$MODE" == "quick" ]]; then
    bash "$ROOT/setup-env.sh" --no-prompt
  else
    bash "$ROOT/setup-env.sh"
  fi
}

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------
docker_install() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker is required. Install Docker Desktop or docker-engine and try again."
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose v2 is required (docker compose). Update Docker."
    exit 1
  fi

  write_env

  step "Building and starting the Docker stack"
  docker compose -f deploy/compose/docker-compose.aio.yml up -d --build
  ok "Stack is up"

  echo ""
  echo "Bootstrapping admin user…"
  if [[ "$NO_PROMPT" -eq 1 || "$MODE" == "quick" ]]; then
    # Non-interactive admin: random 16-char password printed once.
    PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || true)"
    docker compose -f deploy/compose/docker-compose.aio.yml exec -T \
      -e ADMIN_PW="$PW" pharos python /code/scripts/bootstrap_admin.py
    cat <<EOF

${C_GREEN}Admin account created.${C_OFF}
  username: admin
  password: $PW

Save this password — it will not be shown again.
EOF
  else
    docker compose -f deploy/compose/docker-compose.aio.yml exec pharos \
      pharos adduser admin --admin || warn "(admin may already exist)"
  fi

  echo ""
  echo "${C_GREEN}Pharos is running.${C_OFF}"
  echo "  Frontend : http://localhost:3000"
  echo "  API      : http://localhost:8000/docs"
  echo ""
  echo "Tail the logs:   docker compose -f deploy/compose/docker-compose.aio.yml logs -f"
  echo "Stop the stack:  docker compose -f deploy/compose/docker-compose.aio.yml down"
}

# -----------------------------------------------------------------------------
# Native
# -----------------------------------------------------------------------------
native_install() {
  step "Checking Python"
  if ! command -v python3 >/dev/null 2>&1; then
    err "Python 3.11+ is required (python3 not found)."; exit 1
  fi
  PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  ok "Found python3 $PY_VERSION"
  case "$PY_VERSION" in
    3.11|3.12|3.13|3.14) ;;
    *) warn "Pharos targets Python 3.11+; $PY_VERSION may not be supported." ;;
  esac

  if [[ ! -d .venv ]]; then
    step "Creating virtual environment at .venv"
    python3 -m venv .venv
  else
    step "Reusing existing .venv"
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate

  step "Installing Pharos backend"
  pip install --upgrade pip wheel >/dev/null
  if [[ $DEV -eq 1 ]]; then
    pip install -e './backend[dev]'
  else
    pip install -e ./backend
  fi
  ok "Backend installed"

  write_env

  step "Initializing SQLite databases"
  pharos init

  if [[ "$NO_PROMPT" -eq 0 ]]; then
    echo ""
    read -r -p "Create an admin user now? [Y/n] " yn
    if [[ "${yn:-Y}" =~ ^[Yy] ]]; then
      read -r -p "Username [admin]: " username
      username="${username:-admin}"
      pharos adduser "$username" --admin || warn "User creation failed."
    fi
  fi

  if [[ $WITH_FRONTEND -eq 1 ]]; then
    if ! command -v npm >/dev/null 2>&1; then
      warn "npm not found — skipping frontend install. Install Node 20+ to develop the UI."
    else
      step "Installing frontend dependencies"
      ( cd frontend && npm install )
      ok "Frontend dependencies installed"
    fi
  fi

  cat <<EOF

${C_GREEN}Pharos (native) is ready.${C_OFF}

To run it locally (in separate terminals):
  source .venv/bin/activate
  pharos sweep                   # ingestion
  pharos light                   # LLM enrichment
  pharos notify                  # in-app notifications
  uvicorn pharos.api.app:create_app --factory --reload --port 8000
  cd frontend && npm run dev     # open http://localhost:3000

EOF
}

case "$MODE" in
  docker|quick) docker_install ;;
  native)       native_install ;;
  *) err "Unknown mode: $MODE"; exit 1 ;;
esac
