"""OPML import / export for feed subscriptions."""
from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from pydantic import BaseModel

from ...config import get_settings
from ..deps import CurrentUser, get_current_user, get_db

router = APIRouter(prefix="/opml", tags=["opml"])


class OPMLImportResult(BaseModel):
    added: int
    skipped: int
    folders_created: int
    errors: list[str]


@router.get("/export")
def export_opml(user: CurrentUser = Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)) -> Response:
    rows = conn.execute(
        """
        SELECT f.url, f.title, f.site_url, s.folder, s.custom_title
          FROM subscriptions s
          JOIN feeds f ON f.id = s.feed_id
         WHERE s.user_id = ?
         ORDER BY s.folder, COALESCE(s.custom_title, f.title, f.url)
        """,
        (user.id,),
    ).fetchall()

    folders: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        folder_name = r["folder"] or "Unsorted"
        folders.setdefault(folder_name, []).append(r)

    opml = ET.Element("opml", attrib={"version": "2.0"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = f"Pharos export — {user.username}"
    ET.SubElement(head, "dateCreated").text = datetime.now(timezone.utc).isoformat()
    body = ET.SubElement(opml, "body")

    for folder_name, feeds in sorted(folders.items()):
        folder_elem = ET.SubElement(body, "outline", attrib={
            "text": folder_name, "title": folder_name,
        })
        for r in feeds:
            title = r["custom_title"] or r["title"] or r["url"]
            ET.SubElement(folder_elem, "outline", attrib={
                "type": "rss",
                "text": title,
                "title": title,
                "xmlUrl": r["url"],
                "htmlUrl": r["site_url"] or "",
            })

    xml_str = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(opml, encoding="utf-8")
    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="pharos-{user.username}.opml"'},
    )


@router.post("/import", response_model=OPMLImportResult)
async def import_opml(file: UploadFile = File(...),
                     user: CurrentUser = Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)) -> OPMLImportResult:
    content = await file.read()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid OPML: {e}")

    body = root.find("body")
    if body is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OPML missing <body>")

    s = get_settings()
    added = 0
    skipped = 0
    folders_created = 0
    errors: list[str] = []
    seen_folders = set()

    def process_outline(elem: ET.Element, folder: str = "") -> None:
        nonlocal added, skipped, folders_created
        url = elem.attrib.get("xmlUrl", "").strip()
        if url:
            title = elem.attrib.get("title") or elem.attrib.get("text") or None
            try:
                feed_row = conn.execute(
                    "SELECT id FROM feeds WHERE url = ?", (url,),
                ).fetchone()
                if feed_row:
                    feed_id = feed_row["id"]
                else:
                    cur = conn.execute(
                        "INSERT INTO feeds (url, title, poll_interval_sec) VALUES (?, ?, ?)",
                        (url, title, s.default_feed_poll_interval_sec),
                    )
                    feed_id = int(cur.lastrowid)

                existing = conn.execute(
                    "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ?",
                    (user.id, feed_id),
                ).fetchone()
                if existing:
                    skipped += 1
                else:
                    conn.execute(
                        "INSERT INTO subscriptions (user_id, feed_id, folder, custom_title) "
                        "VALUES (?, ?, ?, ?)",
                        (user.id, feed_id, folder, None),
                    )
                    added += 1
            except Exception as e:
                errors.append(f"{url}: {e}")
        else:
            child_folder = elem.attrib.get("title") or elem.attrib.get("text") or ""
            child_folder = child_folder.strip()
            if child_folder and child_folder not in seen_folders:
                seen_folders.add(child_folder)
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_folders (user_id, name) VALUES (?, ?)",
                        (user.id, child_folder),
                    )
                    folders_created += 1
                except Exception:
                    pass
            for child in elem:
                process_outline(child, child_folder or folder)

    for child in body:
        process_outline(child, "")

    conn.commit()
    return OPMLImportResult(added=added, skipped=skipped, folders_created=folders_created, errors=errors[:50])
