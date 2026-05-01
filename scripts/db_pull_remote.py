"""Pull the live droplet's hot.db / cold.db down to ./data_export_remote/.

Run this whenever you want a local backup of the analyses sitting on
the DO droplet.

Usage:
    python scripts/db_pull_remote.py
    python scripts/db_pull_remote.py --out C:/backups/pharos
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    sys.stderr.write("paramiko is required: pip install paramiko\n")
    sys.exit(1)


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# Credentials live in a gitignored .env at the repo root (see
# scripts/.env.deploy.example). We never hardcode them here.
HOST = os.environ.get("PHAROS_DO_HOST")
USER = os.environ.get("PHAROS_DO_USER", "root")
PASS = os.environ.get("PHAROS_DO_PASSWORD")
KEY  = os.environ.get("PHAROS_DO_KEY")

if not HOST:
    sys.stderr.write("PHAROS_DO_HOST is not set. See scripts/.env.deploy.example.\n")
    sys.exit(2)
if not PASS and not KEY:
    sys.stderr.write(
        "Neither PHAROS_DO_PASSWORD nor PHAROS_DO_KEY is set. See scripts/.env.deploy.example.\n"
    )
    sys.exit(2)

REMOTE_DATA = "/opt/pharos/data"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "data_export_remote")
    args = ap.parse_args()

    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {USER}@{HOST}…")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if KEY:
        client.connect(HOST, username=USER, key_filename=KEY, timeout=20)
    else:
        client.connect(HOST, username=USER, password=PASS, timeout=20)

    try:
        sftp = client.open_sftp()
        try:
            files = [f for f in sftp.listdir(REMOTE_DATA)
                     if f.endswith((".db", ".db-wal", ".db-shm"))]
            if not files:
                print(f"No DB files in {REMOTE_DATA} on the droplet.")
                return 1

            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            target = out / stamp
            target.mkdir(parents=True, exist_ok=True)
            for fname in sorted(files):
                src = f"{REMOTE_DATA}/{fname}"
                dst = target / fname
                print(f"  {src}  ->  {dst}")
                sftp.get(src, str(dst))
            total = sum((target / f).stat().st_size for f in files)
            print(f"\nDone. {len(files)} file(s), {total/1_048_576:.1f} MiB "
                  f"in {target}")
        finally:
            sftp.close()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
