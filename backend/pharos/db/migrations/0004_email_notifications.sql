-- Migration 0004: per-user notification email + per-watch email toggle.
--
-- Adds the plumbing the notifier needs to fan in-app match notifications
-- out to email:
--
--   * users.email                  -- where to send digests for this user
--   * saved_searches.notify_email  -- per-watch "also email me" flag
--   * notifications.email_sent_at  -- bookkeeping so we don't email twice
--
-- SQLite's ALTER TABLE only adds columns; running the migration twice is
-- harmless because schema_version gates re-application.

ALTER TABLE users           ADD COLUMN email          TEXT;
ALTER TABLE saved_searches  ADD COLUMN notify_email   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE notifications   ADD COLUMN email_sent_at  DATETIME;

CREATE INDEX IF NOT EXISTS idx_notifications_pending_email
    ON notifications(watch_id, email_sent_at)
    WHERE email_sent_at IS NULL;

INSERT OR REPLACE INTO schema_version(version) VALUES (4);
