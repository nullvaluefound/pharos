"""Deploy Pharos to the omnoptikon Digital Ocean droplet via paramiko + docker compose.

This script is intentionally **DB-safe by design**. The hot.db / cold.db /
blobs that hold every LLM enrichment Pharos has ever produced live in a
Docker named volume (`compose_pharos_data`) on the droplet. Losing them
means re-spending the OpenAI budget. So this script:

  1. Refuses to run if it cannot find a non-empty `compose_pharos_data` volume
     (unless `--first-time` is passed for a brand-new droplet).
  2. Always tarballs the volume to /opt/pharos/backups/docker-volume-<ts>.tgz
     BEFORE doing anything else.
  3. Records the pre-deploy hot.db size + user count + article count, and
     verifies they are unchanged at the end. Refuses to declare success if
     the article count drops.
  4. Uses ONLY the safe compose verbs: `build` and `up -d`. Never `down -v`,
     never `--renew-anon-volumes`, never `volume rm`, never `volume prune`.
     The compose file's volume is declared `external: true` precisely so
     that even an accidental `down -v` cannot remove it.
  5. Excludes *.db / *.db-wal / *.db-shm from the SFTP source upload so a
     stray code rsync can never overwrite a live DB on disk either.

Usage:

  python scripts/deploy_do.py                  # the safe default: snapshot,
                                               # rsync source, rebuild, up -d,
                                               # verify
  python scripts/deploy_do.py --no-source      # skip code rsync (just rebuild
                                               # + recreate from existing
                                               # /opt/pharos sources)
  python scripts/deploy_do.py --no-build       # don't rebuild images;
                                               # just `up -d` to recreate
                                               # containers with current
                                               # images
  python scripts/deploy_do.py --frontend-only  # rebuild + recreate ONLY the
                                               # frontend service
  python scripts/deploy_do.py --backend-only   # rebuild + recreate ONLY the
                                               # backend (pharos) service
  python scripts/deploy_do.py --first-time     # allow deploying when no DB
                                               # volume exists yet (creates
                                               # an empty one)
  python scripts/deploy_do.py --restore <tgz>  # restore the volume from a
                                               # snapshot taken by this script
                                               # (overwrites current DB!)

Local prerequisites:
  pip install paramiko
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import paramiko
except ImportError:
    sys.stderr.write("paramiko is required. pip install paramiko\n")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Configuration (env-only -- never hardcode secrets in this file)
# -----------------------------------------------------------------------------
# Load from a gitignored .env at repo root if present so the credentials
# never sit in tracked source. (Falls back to whatever is already in the
# process env, e.g. set by the shell or an external secret manager.)
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # Don't clobber values explicitly set in the shell.
        os.environ.setdefault(k, v)


_load_dotenv()

HOST = os.environ.get("PHAROS_DO_HOST")
USER = os.environ.get("PHAROS_DO_USER", "root")
PASS = os.environ.get("PHAROS_DO_PASSWORD")
KEY  = os.environ.get("PHAROS_DO_KEY")  # optional path to a private key

if not HOST:
    sys.stderr.write(
        "PHAROS_DO_HOST is not set. Add it to your local .env (gitignored) or "
        "export it in your shell. See scripts/.env.deploy.example.\n"
    )
    sys.exit(2)
if not PASS and not KEY:
    sys.stderr.write(
        "Neither PHAROS_DO_PASSWORD nor PHAROS_DO_KEY is set. Configure one "
        "in your local .env (gitignored). See scripts/.env.deploy.example.\n"
    )
    sys.exit(2)

REMOTE_DIR    = "/opt/pharos"
COMPOSE_FILE  = f"{REMOTE_DIR}/deploy/compose/docker-compose.aio.yml"
COMPOSE_DIR   = f"{REMOTE_DIR}/deploy/compose"
BACKUP_DIR    = f"{REMOTE_DIR}/backups"
VOLUME_NAME   = "compose_pharos_data"  # MUST match docker-compose.aio.yml
PUBLIC_HOST   = "omnoptikon.com"

LOCAL_DIR = Path(__file__).resolve().parent.parent

# CRITICAL: never SFTP a *.db file. The DB lives in the docker volume, not in
# /opt/pharos/, but we never want a wayward .db in the working tree to clobber
# anything either. Same for the .env / private keys / agent transcripts /
# build artifacts that should never go to the droplet.
SKIP = {
    ".venv", "venv", "__pycache__", ".git", ".cursor",
    "node_modules", "dist", "data_export", "data_export_remote",
    "blobs", "frontend.legacy", ".next", "out", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
    "agent-tools", "agent-transcripts", "mcps", "terminals", "assets",
    "build", ".eggs",
}
# Path-prefix exclusions: directories at these *exact* relative paths are
# never uploaded, but identically-named subdirectories deeper in the tree
# (e.g. backend/pharos/lantern/data, where we ship the MITRE + Malpedia
# catalogs) ARE shipped. Use forward slashes regardless of host OS.
SKIP_RELPATHS = {
    "data",                   # project-root runtime DB / blob dir
    "data/blobs",
    "data/exports",
}
SKIP_EXTENSIONS = {".pyc", ".pyo", ".log", ".db", ".db-wal", ".db-shm",
                   ".tsbuildinfo"}
SKIP_FILENAMES  = {".env", ".DS_Store", "Thumbs.db", "id_ed25519",
                   "id_ed25519.pub", "id_ed25519_new", "id_ed25519_new.pub"}

# Files that need CRLF -> LF normalization before being uploaded (otherwise
# bash on the droplet can't find /bin/sh\r). See _safe_put().
TEXT_EXT_LF = {".sh", ".py", ".service", ".timer", ".conf", ".yaml", ".yml",
               ".toml", ".env", ".cfg", ".ini", ".sql", ".md"}


# -----------------------------------------------------------------------------
# SSH helpers
# -----------------------------------------------------------------------------
def _safe_print(prefix: str, body: str, limit: int = 2000) -> None:
    try:
        text = body.strip()[:limit].encode("ascii", "replace").decode("ascii")
        print(f"{prefix}{text}")
    except Exception as e:  # pragma: no cover
        print(f"{prefix}<unprintable: {e}>")


def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if KEY:
        client.connect(HOST, username=USER, key_filename=KEY, timeout=20)
    else:
        client.connect(HOST, username=USER, password=PASS, timeout=20)
    return client


def run(client, cmd, *, check=True, quiet=False, timeout=900):
    if not quiet:
        _safe_print("  $ ", cmd, limit=4000)
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if not quiet and out.strip():
        _safe_print("    ", out)
    if not quiet and err.strip() and code != 0:
        _safe_print("    STDERR: ", err, limit=1000)
    if check and code != 0:
        _safe_print("    EXIT CODE: ", str(code))
    return out, err, code


def _safe_put(sftp, local: str, remote: str) -> None:
    """SFTP-put a single file. Strips CRLF from text-ish files."""
    if any(local.lower().endswith(ext) for ext in TEXT_EXT_LF):
        with open(local, "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")
        with sftp.open(remote, "wb") as rf:
            rf.write(data)
    else:
        sftp.put(local, remote)


def _mkdir_p(sftp, remote_path: str) -> None:
    parts = remote_path.lstrip("/").split("/")
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}"
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def upload_tree(sftp, local_root, remote_root):
    """Recursively SFTP-upload local_root -> remote_root, skipping noise."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(local_root):
        rel = os.path.relpath(dirpath, local_root).replace("\\", "/")
        # Filter children: drop SKIP names AND drop any whose relative path
        # is in SKIP_RELPATHS (so project-root `data/` is excluded but
        # `backend/pharos/lantern/data/` is not).
        kept = []
        for d in dirnames:
            if d in SKIP:
                continue
            child_rel = d if rel == "." else f"{rel}/{d}"
            if child_rel in SKIP_RELPATHS:
                continue
            kept.append(d)
        dirnames[:] = kept

        remote_path = f"{remote_root}/{rel}" if rel != "." else remote_root
        _mkdir_p(sftp, remote_path)
        for fname in filenames:
            if fname in SKIP_FILENAMES:
                continue
            if any(fname.endswith(e) for e in SKIP_EXTENSIONS):
                continue
            _safe_put(sftp, os.path.join(dirpath, fname),
                      f"{remote_path}/{fname}")
            count += 1
    return count


# -----------------------------------------------------------------------------
# DB-safety helpers
# -----------------------------------------------------------------------------
def volume_exists(client) -> bool:
    out, _, _ = run(client,
                    f"docker volume inspect {VOLUME_NAME} >/dev/null 2>&1 "
                    f"&& echo yes || echo no",
                    check=False, quiet=True)
    return "yes" in out


def volume_create(client) -> None:
    print(f"\n  creating brand-new volume: {VOLUME_NAME}")
    run(client, f"docker volume create {VOLUME_NAME}")


_VOLUME_STATE_PY = """\
import sqlite3, os, sys
p = '/data/hot.db'
size = os.path.getsize(p) if os.path.exists(p) else 0
u = a = e = 0
err = ''
try:
    # `?immutable=1` lets sqlite skip the journal/WAL recovery dance and
    # is safe here because we never write. Plain `?mode=ro` will refuse to
    # open if there's a -wal sidecar from the live writer.
    db = sqlite3.connect('file:' + p + '?immutable=1', uri=True)
    u = db.execute('select count(*) from users').fetchone()[0]
    a = db.execute('select count(*) from articles').fetchone()[0]
    e = db.execute("select count(*) from articles where overview is not null").fetchone()[0]
    db.close()
except Exception as ex:
    err = repr(ex)
print(str(size) + '|' + str(u) + '|' + str(a) + '|' + str(e))
if err:
    sys.stderr.write(err + '\\n')
"""


def volume_state(client) -> dict:
    """Return the live volume's headline metrics.

    Approach: drop the inspection script on the droplet's host filesystem,
    then `docker run --rm` a python image with both the volume *and* the
    script bind-mounted in. This works whether or not the pharos container
    is currently running (during a rebuild it's stopped).
    """
    script_remote = "/tmp/_pharos_volume_state.py"
    sftp = client.open_sftp()
    try:
        with sftp.open(script_remote, "wb") as f:
            f.write(_VOLUME_STATE_PY.encode())
    finally:
        sftp.close()

    out, _, code = run(client,
        f"docker run --rm "
        f"-v {VOLUME_NAME}:/data:ro "
        f"-v {script_remote}:/inspect.py:ro "
        f"python:3.12-slim python /inspect.py",
        check=False, quiet=True, timeout=180)

    # Fallback (kept for clarity but rarely triggered).
    if code != 0 or "|" not in out:
        out, _, code = run(client,
            f"docker run --rm "
            f"-v {VOLUME_NAME}:/data:ro "
            f"-v {script_remote}:/inspect.py:ro "
            f"python:3.12-slim python /inspect.py",
            check=False, quiet=True, timeout=180)

    last = (out.strip().splitlines() or [""])[-1]
    parts = last.strip().split("|")
    if len(parts) != 4:
        return {"size": 0, "users": 0, "articles": 0, "enriched": 0}
    try:
        return {
            "size":     int(parts[0] or 0),
            "users":    int(parts[1] or 0),
            "articles": int(parts[2] or 0),
            "enriched": int(parts[3] or 0),
        }
    except ValueError:
        return {"size": 0, "users": 0, "articles": 0, "enriched": 0}


def snapshot_volume(client) -> str:
    """Tarball the entire volume to /opt/pharos/backups/<ts>.tgz."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    name = f"docker-volume-{ts}.tgz"
    run(client, f"mkdir -p {BACKUP_DIR}")
    run(client,
        f"docker run --rm "
        f"-v {VOLUME_NAME}:/data:ro "
        f"-v {BACKUP_DIR}:/backup "
        f"alpine:3.20 sh -c "
        f"\"tar -C /data -czf /backup/{name} . && ls -lh /backup/{name}\"",
        timeout=600)
    print(f"\n  snapshot: {BACKUP_DIR}/{name}")
    # Garbage-collect: keep the most recent 10 snapshots so /opt doesn't fill up.
    run(client,
        f"ls -1t {BACKUP_DIR}/docker-volume-*.tgz 2>/dev/null | "
        f"tail -n +11 | xargs -r rm --",
        check=False, quiet=True)
    return f"{BACKUP_DIR}/{name}"


def restore_volume(client, snapshot_path: str) -> None:
    """Replace the volume's contents with a snapshot. DESTRUCTIVE."""
    print(f"\n  RESTORING volume from {snapshot_path}")
    print( "  this will WIPE current volume contents and replace with snapshot.")
    print( "  bringing the stack down so nothing is mid-write...")
    run(client, f"cd {COMPOSE_DIR} && docker compose -f {COMPOSE_FILE} stop")
    run(client,
        f"docker run --rm "
        f"-v {VOLUME_NAME}:/data "
        f"-v {BACKUP_DIR}:/backup:ro "
        f"alpine:3.20 sh -c "
        f"\"rm -rf /data/* /data/.[!.]* 2>/dev/null; "
        f"tar -C /data -xzf {snapshot_path} && ls -la /data\"",
        timeout=600)
    print( "  bringing the stack back up...")
    run(client, f"cd {COMPOSE_DIR} && docker compose -f {COMPOSE_FILE} up -d")


# -----------------------------------------------------------------------------
# Main deploy flow
# -----------------------------------------------------------------------------
def fmt_state(s: dict) -> str:
    return (f"hot.db={s['size']/1e6:.1f} MB, "
            f"users={s['users']}, "
            f"articles={s['articles']}, "
            f"enriched={s['enriched']}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--no-source", action="store_true",
                    help="Don't rsync source files; just rebuild images and "
                         "recreate containers from what's already on the droplet.")
    ap.add_argument("--no-build", action="store_true",
                    help="Don't `docker compose build`; just `up -d` (fast).")
    ap.add_argument("--frontend-only", action="store_true",
                    help="Rebuild + recreate only the frontend service.")
    ap.add_argument("--backend-only", action="store_true",
                    help="Rebuild + recreate only the pharos backend service.")
    ap.add_argument("--first-time", action="store_true",
                    help="Allow deploying when the DB volume doesn't exist yet "
                         "(will create an empty volume).")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="Skip the pre-deploy DB snapshot. NOT recommended; "
                         "use only for fast iteration on a dev droplet.")
    ap.add_argument("--restore", metavar="SNAPSHOT", default=None,
                    help="Restore the DB volume from a snapshot taken by this "
                         "script (e.g. /opt/pharos/backups/docker-volume-XXX.tgz). "
                         "DESTRUCTIVE -- overwrites the current DB.")
    args = ap.parse_args()

    if args.frontend_only and args.backend_only:
        sys.exit("--frontend-only and --backend-only are mutually exclusive")

    print(f"\nConnecting to {USER}@{HOST}…")
    client = connect()

    # ── Restore short-circuit ────────────────────────────────────────────
    if args.restore:
        if not args.no_snapshot:
            print(f"\n[*] Pre-restore safety snapshot of CURRENT volume…")
            snapshot_volume(client)
        restore_volume(client, args.restore)
        post = volume_state(client)
        print(f"\nRestored. Volume now: {fmt_state(post)}")
        client.close()
        return 0

    # ── 1. Pre-flight: confirm the DB volume is healthy ─────────────────
    print(f"\n[1/7] Pre-flight: checking volume {VOLUME_NAME}")
    if not volume_exists(client):
        if args.first_time:
            volume_create(client)
        else:
            print(f"\n    ERROR: volume {VOLUME_NAME} doesn't exist on the droplet.")
            print( "    If this is a brand-new droplet, re-run with --first-time.")
            client.close()
            return 2

    pre_state = volume_state(client)
    print(f"    pre-deploy state: {fmt_state(pre_state)}")
    if not args.first_time and pre_state["size"] < 1024:
        print(f"\n    ERROR: hot.db is suspiciously small ({pre_state['size']} bytes).")
        print( "    Refusing to deploy on top of an apparently-empty volume.")
        print( "    Pass --first-time if this really IS a fresh droplet.")
        client.close()
        return 3

    # ── 2. Snapshot ─────────────────────────────────────────────────────
    print(f"\n[2/7] Snapshotting volume to {BACKUP_DIR}/")
    if args.no_snapshot:
        print("    SKIPPED (--no-snapshot)")
        snapshot_path = None
    else:
        snapshot_path = snapshot_volume(client)

    # ── 3. SFTP source ──────────────────────────────────────────────────
    print(f"\n[3/7] Uploading project source to {REMOTE_DIR}/  "
          f"(skips *.db, *.db-wal, *.db-shm, .env, .git, dist, node_modules)")
    if args.no_source:
        print("    SKIPPED (--no-source)")
    else:
        run(client, f"mkdir -p {REMOTE_DIR}")
        sftp = client.open_sftp()
        try:
            n = upload_tree(sftp, str(LOCAL_DIR), REMOTE_DIR)
            print(f"    uploaded {n} files")

            # Upload .env separately (and chmod 600). It's in SKIP_FILENAMES
            # for upload_tree.
            env_local = LOCAL_DIR / ".env"
            if env_local.exists():
                _safe_put(sftp, str(env_local), f"{REMOTE_DIR}/.env")
                run(client, f"chmod 600 {REMOTE_DIR}/.env", quiet=True)
                print("    .env uploaded (chmod 600)")
            else:
                print("    NOTE: no local .env; remote .env left as-is")
        finally:
            sftp.close()

    # ── 4. Build ────────────────────────────────────────────────────────
    services = []
    if args.frontend_only:
        services = ["frontend"]
    elif args.backend_only:
        services = ["pharos"]
    svc_args = " ".join(services)

    print(f"\n[4/7] docker compose build  "
          f"{'(' + svc_args + ')' if svc_args else '(all services)'}")
    if args.no_build:
        print("    SKIPPED (--no-build)")
    else:
        out, _, code = run(client,
            f"cd {COMPOSE_DIR} && docker compose -f {COMPOSE_FILE} build "
            f"--pull {svc_args}",
            check=False, timeout=1800)
        if code != 0:
            print("\n    BUILD FAILED. Stack was NOT recreated; "
                  "your data is safe in the volume snapshot.")
            print(f"    Snapshot: {snapshot_path}")
            client.close()
            return 4

    # ── 5. up -d (NEVER -v, NEVER --renew-anon-volumes) ─────────────────
    print(f"\n[5/7] docker compose up -d  "
          f"{'(' + svc_args + ')' if svc_args else '(all services)'}")
    out, _, code = run(client,
        f"cd {COMPOSE_DIR} && docker compose -f {COMPOSE_FILE} up -d {svc_args}",
        check=False, timeout=600)
    if code != 0:
        print("\n    `up -d` FAILED. Try ssh + investigate; data is safe in")
        print(f"    {snapshot_path}")
        client.close()
        return 5
    time.sleep(5)
    run(client, f"cd {COMPOSE_DIR} && docker compose -f {COMPOSE_FILE} ps",
        check=False)

    # ── 6. Verify volume hasn't shrunk / lost data ──────────────────────
    print(f"\n[6/7] Post-deploy verification")
    post_state = volume_state(client)
    print(f"    pre-deploy : {fmt_state(pre_state)}")
    print(f"    post-deploy: {fmt_state(post_state)}")

    if not args.first_time:
        # Article + user counts must NOT decrease. They may grow (sweep keeps
        # polling); never accept a loss.
        bad = []
        if post_state["users"]    < pre_state["users"]:
            bad.append(f"users dropped {pre_state['users']} -> {post_state['users']}")
        if post_state["articles"] < pre_state["articles"]:
            bad.append(f"articles dropped {pre_state['articles']} -> {post_state['articles']}")
        if post_state["enriched"] < pre_state["enriched"]:
            bad.append(f"enriched dropped {pre_state['enriched']} -> {post_state['enriched']}")
        if bad:
            print("    *** DATA LOSS DETECTED ***")
            for line in bad:
                print(f"      - {line}")
            print(f"    Restore with:  python scripts/deploy_do.py "
                  f"--restore {snapshot_path}")
            client.close()
            return 6
        else:
            print("    OK: no data loss (counts unchanged or grew)")

    # ── 7. Smoke test the public URL ────────────────────────────────────
    print(f"\n[7/7] Smoke test")
    out, _, _ = run(client,
        f"curl -sS -o /dev/null -w '%{{http_code}}' -m 8 "
        f"https://{PUBLIC_HOST}/", check=False, quiet=True)
    print(f"    GET https://{PUBLIC_HOST}/  ->  HTTP {out.strip()}")
    out, _, _ = run(client,
        f"curl -sS -m 8 https://{PUBLIC_HOST}/api/v1/auth/login "
        f"-X POST -H 'Content-Type: application/json' -d '{{}}' "
        f"-o /dev/null -w '%{{http_code}}'",
        check=False, quiet=True)
    print(f"    POST /api/v1/auth/login  ->  HTTP {out.strip()} "
          f"(expect 401 or 422 = route reachable)")

    # ── Done ────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print(f"DEPLOY OK")
    print(f"  URL      : https://{PUBLIC_HOST}/")
    if snapshot_path:
        print(f"  Snapshot : {snapshot_path}")
        print(f"  Restore  : python scripts/deploy_do.py --restore {snapshot_path}")
    print(f"  Logs     : ssh {USER}@{HOST} "
          f"'docker logs -f --tail 50 compose-pharos-1'")
    print(f"{'='*64}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
