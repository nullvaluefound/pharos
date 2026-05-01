"""Reset all articles to pending so the Lantern re-enriches them with the current model."""
import sqlite3

conn = sqlite3.connect("/data/hot.db")
conn.row_factory = sqlite3.Row

# Ensure user_folders table exists
conn.executescript("""
CREATE TABLE IF NOT EXISTS user_folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_uf_user ON user_folders(user_id);
""")
print("user_folders table ensured.")

# Update existing feeds poll interval to 4 hours
cur = conn.execute("UPDATE feeds SET poll_interval_sec = 14400")
print(f"Updated {cur.rowcount} feeds to 4-hour poll interval")

# Count articles
total = conn.execute("SELECT COUNT(*) AS c FROM articles").fetchone()["c"]
enriched = conn.execute(
    "SELECT COUNT(*) AS c FROM articles WHERE enrichment_status = 'enriched'"
).fetchone()["c"]
print(f"Total articles: {total}, already enriched: {enriched}")

# Reset all enriched/failed articles to pending
cur2 = conn.execute(
    "UPDATE articles SET enrichment_status = 'pending' "
    "WHERE enrichment_status IN ('enriched', 'failed')"
)
print(f"Reset {cur2.rowcount} articles to pending for re-enrichment")

conn.commit()
conn.close()
print("Done. The Lantern scheduler will pick them up automatically.")
