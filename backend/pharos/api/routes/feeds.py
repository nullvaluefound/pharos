"""Feed subscription management."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from ...config import get_settings
from ...feeds import load_catalog, seed_user
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/feeds", tags=["feeds"])


class FeedIn(BaseModel):
    url: HttpUrl
    folder: str = Field(default="", max_length=64)
    custom_title: str | None = Field(default=None, max_length=200)


class FeedOut(BaseModel):
    id: int
    url: str
    title: str | None
    site_url: str | None
    folder: str
    custom_title: str | None
    last_polled_at: str | None
    last_status: str | None
    error_count: int
    is_active: int = 1


class FolderOut(BaseModel):
    name: str
    feed_count: int


class FolderCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class FolderRenameIn(BaseModel):
    old_name: str = Field(min_length=1, max_length=64)
    new_name: str = Field(min_length=1, max_length=64)


class FeedMoveIn(BaseModel):
    folder: str = Field(max_length=64)


class FeedUpdateIn(BaseModel):
    folder: str | None = Field(default=None, max_length=64)
    custom_title: str | None = Field(default=None, max_length=200)


@router.get("", response_model=list[FeedOut])
def list_feeds(user: CurrentUser = Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)) -> list[FeedOut]:
    rows = conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, s.folder, s.custom_title,
               f.last_polled_at, f.last_status, f.error_count, COALESCE(f.is_active, 1) AS is_active
          FROM subscriptions s
          JOIN feeds f ON f.id = s.feed_id
         WHERE s.user_id = ?
         ORDER BY
            -- Honor user-defined folder order via user_folders.position when set,
            -- otherwise fall back to alphabetical.
            (SELECT COALESCE(uf.position, 999999)
               FROM user_folders uf
              WHERE uf.user_id = s.user_id AND uf.name = NULLIF(s.folder, '')
              LIMIT 1),
            s.folder,
            COALESCE(s.sort_order, 0),
            COALESCE(s.custom_title, f.title, f.url)
        """,
        (user.id,),
    ).fetchall()
    return [FeedOut(**dict(r)) for r in rows]


@router.get("/folders", response_model=list[FolderOut])
def list_folders(user: CurrentUser = Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)) -> list[FolderOut]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(folder, ''), 'Unsorted') AS name,
               COUNT(*) AS feed_count
          FROM subscriptions
         WHERE user_id = ?
         GROUP BY COALESCE(NULLIF(folder, ''), 'Unsorted')
        """,
        (user.id,),
    ).fetchall()
    result = {r["name"]: FolderOut(name=r["name"], feed_count=r["feed_count"]) for r in rows}
    # Include user-created empty folders
    empty = conn.execute(
        "SELECT name FROM user_folders WHERE user_id = ?",
        (user.id,),
    ).fetchall()
    for r in empty:
        if r["name"] not in result:
            result[r["name"]] = FolderOut(name=r["name"], feed_count=0)

    # Order by user_folders.position when set; fall back to alphabetical.
    positions = {
        r["name"]: int(r["position"] or 0)
        for r in conn.execute(
            "SELECT name, position FROM user_folders WHERE user_id = ?",
            (user.id,),
        )
    }
    return sorted(
        result.values(),
        key=lambda f: (positions.get(f.name, 999999), f.name.lower()),
    )


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
def create_folder(data: FolderCreateIn,
                  user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> FolderOut:
    try:
        conn.execute(
            "INSERT INTO user_folders (user_id, name) VALUES (?, ?)",
            (user.id, data.name),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Folder {data.name!r} already exists")
    return FolderOut(name=data.name, feed_count=0)


@router.post("/folders/rename", status_code=status.HTTP_200_OK)
def rename_folder(data: FolderRenameIn,
                  user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    conn.execute(
        "UPDATE subscriptions SET folder = ? WHERE user_id = ? AND folder = ?",
        (data.new_name, user.id, data.old_name),
    )
    conn.execute(
        "UPDATE user_folders SET name = ? WHERE user_id = ? AND name = ?",
        (data.new_name, user.id, data.old_name),
    )
    conn.commit()
    return {"ok": True}


@router.delete("/folders/{folder_name}", status_code=status.HTTP_200_OK)
def delete_folder(folder_name: str,
                  user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Move all feeds in this folder to Unsorted, effectively deleting the folder."""
    cur = conn.execute(
        "UPDATE subscriptions SET folder = '' WHERE user_id = ? AND folder = ?",
        (user.id, folder_name),
    )
    conn.execute(
        "DELETE FROM user_folders WHERE user_id = ? AND name = ?",
        (user.id, folder_name),
    )
    conn.commit()
    return {"ok": True, "moved_to_unsorted": cur.rowcount}


# ---------------------------------------------------------------------------
# Drag-and-drop ordering
# ---------------------------------------------------------------------------
class FolderReorderIn(BaseModel):
    """Replace the user's full folder ordering. Pass folder names in the
    desired display order; positions are assigned 0,1,2,... in that order.

    Folders not present in ``order`` keep their existing position (or
    fall to the end if newly created)."""
    order: list[str] = Field(default_factory=list)


@router.post("/folders/reorder", status_code=status.HTTP_200_OK)
def reorder_folders(data: FolderReorderIn,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Persist a new folder display order via user_folders.position.

    Idempotent. Folders that don't yet have a row in user_folders are
    inserted (so dragging a previously-untracked folder anchors it)."""
    for idx, name in enumerate(data.order):
        if not name or name == "Unsorted":
            continue
        cur = conn.execute(
            "UPDATE user_folders SET position = ? WHERE user_id = ? AND name = ?",
            (idx, user.id, name),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT OR IGNORE INTO user_folders (user_id, name, position) "
                "VALUES (?, ?, ?)",
                (user.id, name, idx),
            )
    conn.commit()
    return {"ok": True, "applied": len(data.order)}


class FeedOrderItem(BaseModel):
    feed_id: int
    folder: str = Field(default="", max_length=64)
    sort_order: int = Field(default=0, ge=0)


class FeedReorderIn(BaseModel):
    """Batch update of (feed_id, folder, sort_order) tuples.

    Used by the drag-and-drop UI to commit a whole reordering in a single
    request after the user releases a drag."""
    items: list[FeedOrderItem]


@router.post("/feeds/reorder", status_code=status.HTTP_200_OK,
             include_in_schema=False)  # legacy mount, kept off public spec
@router.post("/reorder", status_code=status.HTTP_200_OK)
def reorder_feeds(data: FeedReorderIn,
                  user: CurrentUser = Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Persist sort_order + folder for one or more subscriptions in a batch."""
    n = 0
    for item in data.items:
        cur = conn.execute(
            "UPDATE subscriptions SET folder = ?, sort_order = ? "
            "WHERE user_id = ? AND feed_id = ?",
            (item.folder, item.sort_order, user.id, item.feed_id),
        )
        n += cur.rowcount
    conn.commit()
    return {"ok": True, "updated": n}


@router.post("", response_model=FeedOut, status_code=status.HTTP_201_CREATED)
def add_feed(data: FeedIn,
             user: CurrentUser = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)) -> FeedOut:
    s = get_settings()
    url = str(data.url)
    feed_row = conn.execute(
        "SELECT id, url, title, site_url FROM feeds WHERE url = ?", (url,)
    ).fetchone()
    if feed_row:
        feed_id = feed_row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO feeds (url, poll_interval_sec) VALUES (?, ?)",
            (url, s.default_feed_poll_interval_sec),
        )
        feed_id = int(cur.lastrowid)

    conn.execute(
        "INSERT OR REPLACE INTO subscriptions "
        "(user_id, feed_id, folder, custom_title) VALUES (?, ?, ?, ?)",
        (user.id, feed_id, data.folder, data.custom_title),
    )
    conn.commit()

    out = conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, s.folder, s.custom_title,
               f.last_polled_at, f.last_status, f.error_count,
               COALESCE(f.is_active, 1) AS is_active
          FROM subscriptions s JOIN feeds f ON f.id = s.feed_id
         WHERE s.user_id = ? AND s.feed_id = ?
        """,
        (user.id, feed_id),
    ).fetchone()
    return FeedOut(**dict(out))


@router.patch("/{feed_id}", response_model=FeedOut)
def update_subscription(feed_id: int,
                        data: FeedUpdateIn,
                        user: CurrentUser = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)) -> FeedOut:
    sets: list[str] = []
    params: list = []
    if data.folder is not None:
        sets.append("folder = ?")
        params.append(data.folder)
    if data.custom_title is not None:
        sets.append("custom_title = ?")
        params.append(data.custom_title)
    if not sets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    params.extend([user.id, feed_id])
    cur = conn.execute(
        f"UPDATE subscriptions SET {', '.join(sets)} WHERE user_id = ? AND feed_id = ?",
        params,
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    out = conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, s.folder, s.custom_title,
               f.last_polled_at, f.last_status, f.error_count,
               COALESCE(f.is_active, 1) AS is_active
          FROM subscriptions s JOIN feeds f ON f.id = s.feed_id
         WHERE s.user_id = ? AND s.feed_id = ?
        """,
        (user.id, feed_id),
    ).fetchone()
    return FeedOut(**dict(out))


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_subscription(feed_id: int,
                        user: CurrentUser = Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)) -> None:
    cur = conn.execute(
        "DELETE FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user.id, feed_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")


# ---------------------------------------------------------------------------
# Feed health
# ---------------------------------------------------------------------------
class FeedHealth(BaseModel):
    id: int
    url: str
    title: str | None
    last_polled_at: str | None
    last_status: str | None
    error_count: int
    article_count: int
    pending_count: int
    enriched_count: int
    failed_count: int


@router.get("/{feed_id}/health", response_model=FeedHealth)
def feed_health(feed_id: int,
                user: CurrentUser = Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)) -> FeedHealth:
    sub = conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user.id, feed_id),
    ).fetchone()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not subscribed to this feed")
    f = conn.execute(
        "SELECT id, url, title, last_polled_at, last_status, error_count FROM feeds WHERE id = ?",
        (feed_id,),
    ).fetchone()
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feed not found")
    counts = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN enrichment_status = 'pending' THEN 1 ELSE 0 END) AS pending, "
        "SUM(CASE WHEN enrichment_status = 'enriched' THEN 1 ELSE 0 END) AS enriched, "
        "SUM(CASE WHEN enrichment_status = 'failed' THEN 1 ELSE 0 END) AS failed "
        "FROM articles WHERE feed_id = ?",
        (feed_id,),
    ).fetchone()
    return FeedHealth(
        id=f["id"], url=f["url"], title=f["title"],
        last_polled_at=f["last_polled_at"], last_status=f["last_status"],
        error_count=f["error_count"] or 0,
        article_count=int(counts["total"] or 0),
        pending_count=int(counts["pending"] or 0),
        enriched_count=int(counts["enriched"] or 0),
        failed_count=int(counts["failed"] or 0),
    )


class FeedActiveIn(BaseModel):
    is_active: bool


class FeedActiveOut(BaseModel):
    id: int
    is_active: int
    pending_dropped: int  # how many pending articles were purged on pause


@router.patch("/{feed_id}/active", response_model=FeedActiveOut)
def set_feed_active(feed_id: int,
                    data: FeedActiveIn,
                    user: CurrentUser = Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)) -> FeedActiveOut:
    """Pause or resume polling for a feed.

    Pausing (``is_active=False``) flips the global ``feeds.is_active`` flag --
    the ingestion scheduler picks the change up within ~60s and removes the
    poll job. Already-ingested articles stay in the stream; we don't
    retroactively hide them. As a cost-saving side effect, any of THIS
    feed's articles that are still queued for LLM enrichment
    (``enrichment_status='pending'``) are dropped, since the user is
    explicitly saying they don't want this source consuming their budget.

    Authorization: the caller must be subscribed to the feed.
    """
    sub = conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user.id, feed_id),
    ).fetchone()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not subscribed to this feed")

    cur = conn.execute(
        "UPDATE feeds SET is_active = ? WHERE id = ?",
        (1 if data.is_active else 0, feed_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feed not found")

    pending_dropped = 0
    if not data.is_active:
        purge = conn.execute(
            "DELETE FROM articles "
            "WHERE feed_id = ? AND enrichment_status = 'pending'",
            (feed_id,),
        )
        pending_dropped = purge.rowcount or 0

    conn.commit()
    return FeedActiveOut(
        id=feed_id,
        is_active=1 if data.is_active else 0,
        pending_dropped=pending_dropped,
    )


@router.post("/{feed_id}/poll", status_code=status.HTTP_202_ACCEPTED)
def force_poll(feed_id: int,
               user: CurrentUser = Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Reset the next-poll trigger for this feed.

    The actual poll is handled out-of-band by the ingestion scheduler when it
    next re-evaluates feeds. We clear etag/last_modified so the very next poll
    fetches fully.
    """
    sub = conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user.id, feed_id),
    ).fetchone()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not subscribed to this feed")
    conn.execute(
        "UPDATE feeds SET last_polled_at = NULL, etag = NULL, last_modified = NULL "
        "WHERE id = ?", (feed_id,),
    )
    conn.commit()
    return {"ok": True, "queued": True}


# ---------------------------------------------------------------------------
# Curated feed catalog (user-facing)
# ---------------------------------------------------------------------------
class CatalogFeedItem(BaseModel):
    title: str | None
    url: str
    folder: str | None
    tags: list[str] = []


class CatalogCategoryItem(BaseModel):
    id: str
    name: str
    folder: str
    description: str
    enabled_by_default: bool
    feeds: list[CatalogFeedItem]


class CatalogPresetItem(BaseModel):
    id: str
    name: str
    description: str
    categories: list[str]


class CatalogResp(BaseModel):
    categories: list[CatalogCategoryItem]
    presets: list[CatalogPresetItem]


class SeedSelfIn(BaseModel):
    category_ids: list[str] | None = None
    preset_id: str | None = None


@router.get("/catalog", response_model=CatalogResp)
def get_catalog(_: CurrentUser = Depends(get_current_user)) -> CatalogResp:
    cat = load_catalog()
    return CatalogResp(
        categories=[
            CatalogCategoryItem(
                id=c.id, name=c.name, folder=c.folder,
                description=c.description, enabled_by_default=c.enabled_by_default,
                feeds=[CatalogFeedItem(title=f.title, url=f.url,
                                       folder=f.folder, tags=f.tags) for f in c.feeds],
            )
            for c in cat.categories
        ],
        presets=[
            CatalogPresetItem(id=p.id, name=p.name, description=p.description,
                              categories=p.categories)
            for p in cat.presets
        ],
    )


@router.post("/seed", status_code=status.HTTP_200_OK)
def seed_self(data: SeedSelfIn,
              user: CurrentUser = Depends(get_current_user)) -> dict:
    """Subscribe the current user to a chosen subset of the catalog."""
    if data.category_ids and data.preset_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "category_ids and preset_id are mutually exclusive",
        )
    try:
        result = seed_user(
            username=user.username,
            category_ids=data.category_ids,
            preset_id=data.preset_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "added_subscriptions": result.added_subscriptions,
        "skipped_existing": result.skipped_existing,
        "new_feeds": result.new_feeds,
        "by_category": result.by_category,
    }


@router.post("/{feed_id}/retry-failed", status_code=status.HTTP_200_OK)
def retry_failed_articles(feed_id: int,
                          user: CurrentUser = Depends(get_current_user),
                          conn: sqlite3.Connection = Depends(get_db)) -> dict:
    sub = conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user.id, feed_id),
    ).fetchone()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not subscribed to this feed")
    cur = conn.execute(
        "UPDATE articles SET enrichment_status = 'pending', enrichment_error = NULL "
        "WHERE feed_id = ? AND enrichment_status = 'failed'",
        (feed_id,),
    )
    conn.commit()
    return {"ok": True, "reset": cur.rowcount}
