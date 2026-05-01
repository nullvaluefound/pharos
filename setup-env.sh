#!/usr/bin/env bash
# Pharos -- interactive .env bootstrap.
#
# Creates or updates a .env file in the repo root with sensible values:
#   - Prompts for OPENAI_API_KEY (Enter to skip; you can set it later).
#   - Auto-generates a strong JWT_SECRET if it's still the placeholder.
#   - Lets you choose PHAROS_DB_DIR.
#
# This script does not install anything; it only writes .env. Use it before
# `docker compose up` (or before running install.sh, which will call this
# automatically).
#
# Usage:
#   ./setup-env.sh                 # interactive
#   ./setup-env.sh --no-prompt     # generate JWT_SECRET only; leave the rest
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NO_PROMPT=0
for arg in "$@"; do
  case "$arg" in
    --no-prompt|-y) NO_PROMPT=1 ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

C_CYAN='\033[1;36m'; C_GREEN='\033[1;32m'; C_YELLOW='\033[1;33m'; C_OFF='\033[0m'
say()  { echo -e "${C_CYAN}==> $*${C_OFF}"; }
ok()   { echo -e "    ${C_GREEN}$*${C_OFF}"; }
warn() { echo -e "    ${C_YELLOW}$*${C_OFF}"; }

if [[ ! -f .env ]]; then
  say "Creating .env from .env.example"
  cp .env.example .env
  ok "wrote .env"
else
  say "Updating existing .env (placeholders will be replaced)"
fi

# Helper: get/set a key=value pair in .env (in-place).
get_env() {
  local key="$1"
  awk -F'=' -v k="$key" '$1==k { sub(/^[^=]*=/,""); print; exit }' .env
}
set_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if grep -q "^${key}=" .env; then
    awk -F'=' -v k="$key" -v v="$val" \
      'BEGIN{OFS="="} $1==k {print k"="v; next} {print}' .env > "$tmp"
  else
    cat .env > "$tmp"
    echo "${key}=${val}" >> "$tmp"
  fi
  mv "$tmp" .env
}

# ----- JWT_SECRET (auto-generate if placeholder) ------------------------------
current_jwt="$(get_env JWT_SECRET || true)"
if [[ -z "$current_jwt" || "$current_jwt" == *"please-change"* || "$current_jwt" == "dev-secret-change-me" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    new_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
  else
    new_secret="$(LC_ALL=C tr -dc 'A-Za-z0-9_-' </dev/urandom | head -c 86)"
  fi
  set_env JWT_SECRET "$new_secret"
  ok "generated a new JWT_SECRET"
else
  ok "JWT_SECRET already set"
fi

# ----- OPENAI_API_KEY ---------------------------------------------------------
current_key="$(get_env OPENAI_API_KEY || true)"
if [[ -n "$current_key" && "$current_key" != "sk-replace-me" ]]; then
  ok "OPENAI_API_KEY already set"
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  set_env OPENAI_API_KEY "$OPENAI_API_KEY"
  ok "OPENAI_API_KEY picked up from environment"
elif [[ $NO_PROMPT -eq 1 ]]; then
  warn "OPENAI_API_KEY is still the placeholder; edit .env before starting the lantern."
else
  echo ""
  read -r -s -p "Enter your OPENAI_API_KEY (Enter to skip and set later): " api_key
  echo ""
  if [[ -n "$api_key" ]]; then
    set_env OPENAI_API_KEY "$api_key"
    ok "OPENAI_API_KEY saved"
  else
    warn "Skipped. The lantern will fail until you set OPENAI_API_KEY in .env."
  fi
fi

# ----- OPENAI_MODEL (offer override) ------------------------------------------
if [[ $NO_PROMPT -eq 0 ]]; then
  current_model="$(get_env OPENAI_MODEL || true)"
  current_model="${current_model:-gpt-4o-mini}"
  read -r -p "OpenAI model [$current_model]: " new_model
  if [[ -n "$new_model" && "$new_model" != "$current_model" ]]; then
    set_env OPENAI_MODEL "$new_model"
    ok "OPENAI_MODEL set to $new_model"
  fi
fi

# ----- PHAROS_DB_DIR ----------------------------------------------------------
if [[ $NO_PROMPT -eq 0 ]]; then
  current_dir="$(get_env PHAROS_DB_DIR || true)"
  current_dir="${current_dir:-./data}"
  read -r -p "Pharos data directory [$current_dir]: " new_dir
  if [[ -n "$new_dir" && "$new_dir" != "$current_dir" ]]; then
    set_env PHAROS_DB_DIR "$new_dir"
    ok "PHAROS_DB_DIR set to $new_dir"
  fi
fi

echo ""
ok ".env is ready. You can edit it any time."
