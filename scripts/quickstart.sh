#!/usr/bin/env bash
# Pharos one-liner installer.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/nullvaluefound/pharos/main/scripts/quickstart.sh | bash
#
# What it does:
#   1) clones the repo into ~/pharos (or skips if already present)
#   2) runs `./install.sh --quick` (Docker, auto-config, random admin password)
set -euo pipefail

REPO="${PHAROS_REPO:-https://github.com/nullvaluefound/pharos.git}"
DIR="${PHAROS_DIR:-$HOME/pharos}"

if [[ -d "$DIR" ]]; then
  echo "==> Reusing existing checkout at $DIR"
  cd "$DIR" && git pull --ff-only || true
else
  echo "==> Cloning $REPO -> $DIR"
  git clone "$REPO" "$DIR"
  cd "$DIR"
fi

exec ./install.sh --quick
