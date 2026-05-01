-- Migration 0002: feed active flag + per-subscription sort order.
--
-- Adds:
--   feeds.is_active             -- when 0, the scheduler skips polling
--   subscriptions.sort_order    -- per-user, per-folder ordering of feeds
--
-- ALTER TABLE ... ADD COLUMN is idempotent only if guarded by the migration
-- runner -- SQLite has no `IF NOT EXISTS` for columns. The runner checks
-- schema_version before applying.

ALTER TABLE feeds ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;

ALTER TABLE subscriptions ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_feeds_active ON feeds(is_active);
CREATE INDEX IF NOT EXISTS idx_subs_user_folder_order
    ON subscriptions(user_id, folder, sort_order);

INSERT OR REPLACE INTO schema_version(version) VALUES (2);
