"""Create (or look up) the 'admin' user inside the pharos container.

Reads password from $ADMIN_PW. Idempotent: if the user already exists, just
prints its id and exits 0 without touching the password.
"""
import os
import sys

from pharos.api.auth import create_user
from pharos.db import connect, init_databases


def main() -> int:
    pw = os.environ.get("ADMIN_PW")
    if not pw:
        print("ADMIN_PW env var is required", file=sys.stderr)
        return 2

    init_databases()
    with connect(attach_cold=False) as conn:
        row = conn.execute(
            "SELECT id, is_admin FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        if row:
            print(f"admin already exists (id={row['id']}, is_admin={row['is_admin']})")
            return 0
        uid = create_user(conn, username="admin", password=pw, is_admin=True)
        conn.commit()
        print(f"created admin (id={uid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
