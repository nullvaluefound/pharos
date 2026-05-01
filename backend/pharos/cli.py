"""Pharos command-line interface.

Greek-flavored verbs for the workers (sweep, light, archive) and friendly
verbs for management (init, adduser, watch, reprocess).
"""
from __future__ import annotations

import asyncio
import getpass
import logging

import typer
from rich.console import Console
from rich.table import Table

from .archiver.job import archive_once
from .config import get_settings
from .db import connect, init_databases
from .feeds import load_catalog, seed_user
from .ingestion.scheduler import run_forever as run_sweep
from .lantern.worker import run_forever as run_lantern
from .notifier.checker import run_forever as run_notifier

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Pharos CLI")
console = Console()


@app.command()
def init() -> None:
    """Create hot.db and cold.db with the Pharos schema."""
    init_databases()
    s = get_settings()
    console.print(
        f"[green]Initialized[/] databases at "
        f"[bold]{s.hot_db_path}[/] and [bold]{s.cold_db_path}[/]"
    )


@app.command()
def adduser(
    username: str,
    admin: bool = typer.Option(False, "--admin", help="Grant admin privileges"),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Password (non-interactive). Avoid in shared shells; "
             "prefer --password-stdin or the interactive prompt.",
    ),
    password_stdin: bool = typer.Option(
        False,
        "--password-stdin",
        help="Read the password from stdin (single line). Useful for scripts.",
    ),
) -> None:
    """Create a local user.

    By default prompts twice for the password. Pass --password or
    --password-stdin to run non-interactively (e.g. inside docker exec).
    """
    init_databases()
    if password_stdin:
        import sys
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            console.print("[red]Empty password from stdin[/]")
            raise typer.Exit(1)
    elif password is None:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            console.print("[red]Passwords do not match[/]")
            raise typer.Exit(1)
    from .api.auth import create_user
    with connect(attach_cold=False) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            console.print(f"[red]User {username!r} already exists[/]")
            raise typer.Exit(1)
        uid = create_user(conn, username=username, password=password, is_admin=admin)
        conn.commit()
    console.print(f"[green]Created[/] user [bold]{username}[/] (id={uid}, admin={admin})")


@app.command()
def listusers() -> None:
    """List all local users."""
    init_databases()
    with connect(attach_cold=False) as conn:
        rows = conn.execute(
            "SELECT id, username, COALESCE(is_admin,0) AS is_admin, "
            "       created_at "
            "FROM users ORDER BY id"
        ).fetchall()
    table = Table(title="Pharos Users")
    for col in ("id", "username", "admin", "created_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["id"]),
            r["username"],
            "yes" if r["is_admin"] else "no",
            str(r["created_at"] or "-"),
        )
    console.print(table)


@app.command()
def deluser(
    username: str,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the interactive confirmation prompt.",
    ),
) -> None:
    """Delete a local user and ALL of their personal data.

    Cascade-deletes (via FK ON DELETE CASCADE):
      - subscriptions     (which feeds the user follows)
      - user_folders      (custom group definitions)
      - user_article_state (saved/read/seen flags)
      - saved_searches    (Watches)
      - notifications     (in-app delivered watch hits)
      - reports           (generated threat-intel reports)

    Articles, feeds, story_clusters, and the cold archive are SHARED
    across users and are NOT touched -- a deleted user's prior reads
    just lose their per-user state. If you also want the now-orphaned
    feeds (no remaining subscribers) cleaned up, run a separate
    maintenance script; this command intentionally stays surgical.
    """
    init_databases()
    with connect(attach_cold=False) as conn:
        urow = conn.execute(
            "SELECT id, COALESCE(is_admin,0) AS is_admin "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not urow:
            console.print(f"[red]No user named {username!r}[/]")
            raise typer.Exit(1)
        uid = int(urow["id"])

        # Pre-flight: count what will be deleted so the user can audit.
        counts: dict[str, int] = {}
        for table in (
            "subscriptions",
            "user_folders",
            "user_article_state",
            "saved_searches",
            "notifications",
            "reports",
        ):
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = ?",
                    (uid,),
                ).fetchone()
                counts[table] = int(row["c"] or 0)
            except Exception:
                # Table might not exist on older schemas; skip.
                counts[table] = 0

        # Refuse to wipe the last admin -- that's a footgun.
        if urow["is_admin"]:
            other_admins = conn.execute(
                "SELECT COUNT(*) AS c FROM users "
                "WHERE COALESCE(is_admin,0) = 1 AND id != ?",
                (uid,),
            ).fetchone()
            if int(other_admins["c"] or 0) == 0:
                console.print(
                    f"[red]Refusing to delete {username!r}: "
                    f"that's the only admin account.[/]\n"
                    f"[dim]Promote another user first "
                    f"(or pass --yes after creating another admin).[/]"
                )
                if not yes:
                    raise typer.Exit(1)

        # Show the impact summary.
        table = Table(title=f"Will delete user {username!r} (id={uid}) plus:")
        table.add_column("table")
        table.add_column("rows", justify="right")
        for k, v in counts.items():
            table.add_row(k, str(v))
        console.print(table)

        if not yes:
            confirm = typer.confirm(
                f"Permanently delete {username!r} and all listed rows?",
                default=False,
            )
            if not confirm:
                console.print("[yellow]Aborted; nothing changed.[/]")
                raise typer.Exit(0)

        cur = conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()

    if cur.rowcount == 0:
        console.print(f"[red]Delete failed; user {username!r} was not removed.[/]")
        raise typer.Exit(1)

    console.print(
        f"[green]Deleted[/] user [bold]{username}[/] (id={uid}) "
        f"and {sum(counts.values())} cascaded row(s)."
    )


@app.command()
def watch(
    feed_url: str,
    user: str = typer.Option(..., "--user", "-u", help="Username that should subscribe"),
    folder: str = typer.Option("", "--folder", "-f"),
) -> None:
    """Subscribe USER to FEED_URL."""
    init_databases()
    s = get_settings()
    with connect(attach_cold=False) as conn:
        urow = conn.execute("SELECT id FROM users WHERE username = ?", (user,)).fetchone()
        if not urow:
            console.print(f"[red]No user named {user!r}; run 'pharos adduser' first[/]")
            raise typer.Exit(1)
        feed = conn.execute(
            "SELECT id FROM feeds WHERE url = ?", (feed_url,)
        ).fetchone()
        if feed:
            feed_id = feed["id"]
        else:
            cur = conn.execute(
                "INSERT INTO feeds (url, poll_interval_sec) VALUES (?, ?)",
                (feed_url, s.default_feed_poll_interval_sec),
            )
            feed_id = int(cur.lastrowid)
        conn.execute(
            "INSERT OR REPLACE INTO subscriptions(user_id, feed_id, folder) VALUES (?, ?, ?)",
            (urow["id"], feed_id, folder),
        )
        conn.commit()
    console.print(f"[green]Subscribed[/] user [bold]{user}[/] to feed id {feed_id}: {feed_url}")


@app.command()
def feeds() -> None:
    """List all feeds and their status."""
    init_databases()
    with connect(attach_cold=False) as conn:
        rows = conn.execute(
            "SELECT id, url, COALESCE(title,'') AS title, last_polled_at, "
            "last_status, error_count FROM feeds ORDER BY id"
        ).fetchall()
    table = Table(title="Pharos Feeds")
    for col in ("id", "title", "url", "last_polled_at", "last_status", "errors"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["id"]), r["title"][:40], r["url"][:60],
            str(r["last_polled_at"] or "-"), str(r["last_status"] or "-"),
            str(r["error_count"]),
        )
    console.print(table)


@app.command()
def status() -> None:
    """Show pipeline status (article counts by enrichment status)."""
    init_databases()
    with connect() as conn:
        hot = conn.execute(
            "SELECT enrichment_status, COUNT(*) AS c FROM main.articles GROUP BY 1"
        ).fetchall()
        cold = conn.execute("SELECT COUNT(*) AS c FROM cold.articles").fetchone()
    table = Table(title="Pharos Pipeline")
    table.add_column("status")
    table.add_column("count", justify="right")
    for r in hot:
        table.add_row(r["enrichment_status"], str(r["c"]))
    table.add_row("[dim]archived (cold)[/]", str(cold["c"] if cold else 0))
    console.print(table)


@app.command()
def sweep() -> None:
    """Run the ingestion scheduler (Stage 1) in the foreground."""
    logging.basicConfig(level=get_settings().log_level)
    init_databases()
    asyncio.run(run_sweep())


@app.command()
def light() -> None:
    """Run the lantern (Stage 2: LLM enrichment) in the foreground."""
    logging.basicConfig(level=get_settings().log_level)
    init_databases()
    asyncio.run(run_lantern())


@app.command()
def notify() -> None:
    """Run the watch checker (delivers in-app notifications)."""
    logging.basicConfig(level=get_settings().log_level)
    init_databases()
    asyncio.run(run_notifier())


@app.command()
def archive() -> None:
    """Run the archiver (Stage 3) once."""
    logging.basicConfig(level=get_settings().log_level)
    init_databases()
    moved = archive_once()
    console.print(f"[green]Archived[/] {moved} articles to the archeion")


@app.command(name="catalog")
def show_catalog() -> None:
    """List the bundled curated feed catalog (categories + presets)."""
    cat = load_catalog()
    table = Table(title="Pharos Feed Catalog -- Categories")
    for col in ("id", "name", "feeds", "default", "description"):
        table.add_column(col)
    for c in cat.categories:
        table.add_row(
            c.id, c.name, str(len(c.feeds)),
            "yes" if c.enabled_by_default else "no",
            c.description[:80],
        )
    console.print(table)

    p_table = Table(title="Pharos Feed Catalog -- Presets")
    for col in ("id", "name", "categories", "description"):
        p_table.add_column(col)
    for p in cat.presets:
        p_table.add_row(p.id, p.name, ",".join(p.categories), p.description[:80])
    console.print(p_table)


@app.command(name="seed-feeds")
def seed_feeds(
    user: str = typer.Option(..., "--user", "-u", help="Username to subscribe."),
    categories: str | None = typer.Option(
        None,
        "--categories",
        "-c",
        help="Comma-separated category ids (e.g. government,vendors,news). "
             "Mutually exclusive with --preset.",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        "-p",
        help="Apply a preset (e.g. starter, minimal, full, everything). "
             "Mutually exclusive with --categories.",
    ),
    list_only: bool = typer.Option(
        False, "--list", help="Just list what would be added; do not modify the DB."
    ),
) -> None:
    """Subscribe USER to the bundled curated feeds.

    Examples:
        pharos seed-feeds -u alice                      # default categories
        pharos seed-feeds -u alice -p starter           # the 'starter' preset
        pharos seed-feeds -u alice -c government,news   # explicit categories
        pharos seed-feeds -u alice --list               # preview, do not write
    """
    if categories and preset:
        console.print("[red]--categories and --preset are mutually exclusive[/]")
        raise typer.Exit(2)
    init_databases()

    cat_ids = [c.strip() for c in categories.split(",")] if categories else None

    if list_only:
        catalog = load_catalog()
        chosen_ids = (
            cat_ids
            or (catalog.preset(preset).categories if preset else
                [c.id for c in catalog.categories if c.enabled_by_default])
        )
        for cid in chosen_ids:
            c = catalog.category(cid)
            if not c:
                console.print(f"[red]Unknown category: {cid}[/]")
                continue
            console.print(f"[bold beam]{c.name}[/] ({len(c.feeds)} feeds)")
            for f in c.feeds:
                console.print(f"  - {f.title or f.url}")
        return

    try:
        result = seed_user(username=user, category_ids=cat_ids, preset_id=preset)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    table = Table(title=f"Seeded feeds for {user}")
    table.add_column("category")
    table.add_column("added", justify="right")
    for cid, n in result.by_category.items():
        table.add_row(cid, str(n))
    console.print(table)
    console.print(
        f"[green]Done.[/] {result.added_subscriptions} new subscription(s), "
        f"{result.new_feeds} new feed row(s), {result.skipped_existing} already present."
    )


@app.command()
def reprocess(
    failed_only: bool = typer.Option(False, "--failed-only", help="Only failed rows"),
    article_id: list[int] = typer.Option(None, "--id", help="Specific article id(s)"),
) -> None:
    """Reset enrichment_status to 'pending' so the lantern re-processes rows."""
    init_databases()
    with connect(attach_cold=False) as conn:
        if article_id:
            placeholders = ",".join("?" * len(article_id))
            cur = conn.execute(
                f"UPDATE articles SET enrichment_status='pending', enrichment_error=NULL "
                f"WHERE id IN ({placeholders})",
                article_id,
            )
        elif failed_only:
            cur = conn.execute(
                "UPDATE articles SET enrichment_status='pending', enrichment_error=NULL "
                "WHERE enrichment_status='failed'"
            )
        else:
            cur = conn.execute(
                "UPDATE articles SET enrichment_status='pending', enrichment_error=NULL "
                "WHERE enrichment_status IN ('failed','in_progress')"
            )
        conn.commit()
    console.print(f"[green]Reset[/] {cur.rowcount} article(s) to pending")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
