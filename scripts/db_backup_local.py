"""Extract Pharos's SQLite DBs out of the local Docker volume into ./data_export/.

Usage:
    python scripts/db_backup_local.py
    python scripts/db_backup_local.py --volume compose_pharos_data --out ./data_export

Why: the local AIO compose stack stores hot.db and cold.db inside a Docker
named volume that lives in the WSL2 VM. To deploy to the DO droplet without
losing the (expensive) LLM analyses, we need to copy them to a regular
folder we can SCP up.

This script does NOT modify the source volume.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_VOLUME = "compose_pharos_data"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data_export"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def docker_running() -> bool:
    try:
        subprocess.run(
            ["docker", "info"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--volume", default=DEFAULT_VOLUME,
                    help=f"Docker named volume that holds hot.db / cold.db "
                         f"(default: {DEFAULT_VOLUME})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--archive-old", action="store_true",
                    help="If --out already exists, move it aside with a timestamp")
    args = ap.parse_args()

    if not docker_running():
        print("ERROR: Docker Desktop is not running. Start it and re-run.", file=sys.stderr)
        return 2

    # Verify the volume exists
    res = subprocess.run(
        ["docker", "volume", "inspect", args.volume],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if res.returncode != 0:
        print(f"ERROR: Docker volume '{args.volume}' not found.", file=sys.stderr)
        print("  Run 'docker volume ls' to list available volumes.", file=sys.stderr)
        return 3

    out: Path = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        if args.archive_old:
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            archived = out.with_name(out.name + f".{stamp}.bak")
            print(f"==> Archiving existing {out} -> {archived}")
            shutil.move(str(out), str(archived))
        else:
            print(f"WARNING: {out} already has files. Pass --archive-old to roll it.",
                  file=sys.stderr)

    out.mkdir(parents=True, exist_ok=True)

    # Use a tiny alpine helper to copy files out of the volume to /backup.
    # We try SQLite's online-backup API first (consistent under load), and
    # fall back to cp if .backup fails (read-only mount, perms, etc.).
    out_mount = str(out).replace("\\", "/")
    print(f"\n==> Copying *.db from volume '{args.volume}' -> {out}")
    run([
        "docker", "run", "--rm",
        # NOT read-only: SQLite .backup opens the source RW even though it
        # only reads, because it needs to acquire shared locks via -shm.
        "-v", f"{args.volume}:/data",
        "-v", f"{out_mount}:/backup",
        "alpine:3.20", "sh", "-c",
        "set -e; "
        "apk add --no-cache sqlite >/dev/null 2>&1 || true; "
        "for f in hot.db cold.db; do "
        "  if [ -f /data/$f ]; then "
        "    if command -v sqlite3 >/dev/null 2>&1 "
        "       && sqlite3 /data/$f \".backup /backup/$f\" 2>/dev/null; then "
        "      echo \"  online-backup: $f\"; "
        "    else "
        "      echo \"  cp:            $f\"; "
        "      cp /data/$f /backup/; "
        "      [ -f /data/${f}-wal ] && cp /data/${f}-wal /backup/ || true; "
        "      [ -f /data/${f}-shm ] && cp /data/${f}-shm /backup/ || true; "
        "    fi; "
        "  fi; "
        "done; "
        "ls -la /backup/",
    ])

    files = sorted(out.glob("*"))
    if not files:
        print("WARNING: nothing was copied. Volume may be empty.", file=sys.stderr)
        return 4

    total = sum(f.stat().st_size for f in files)
    print(f"\n==> Done. {len(files)} file(s), {total/1_048_576:.1f} MiB total")
    for f in files:
        print(f"     {f.name}  ({f.stat().st_size:,} bytes)")
    print(f"\nReady to deploy. Now run:")
    print(f"  python scripts/deploy_do.py --upload-db ./data_export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
