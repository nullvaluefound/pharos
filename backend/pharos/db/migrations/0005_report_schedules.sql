-- Migration 0005: scheduled (recurring) report generation.
--
-- Each row defines a saved report request that the notifier loop runs on
-- a cadence (daily / weekly / monthly), persists as a regular row in
-- `reports`, and -- if the user has email configured -- emails to them.
--
-- We stash the full ReportRequest as JSON so the schedule's payload
-- evolves with the dataclass; no separate column-per-field migrations.

CREATE TABLE IF NOT EXISTS report_schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Display name for the schedule itself (e.g. "Monday Threat Briefing").
    -- The generated report rows use the request's own `name`.
    name            TEXT NOT NULL,
    -- Frozen ReportRequest JSON. See pharos.reports.ReportRequest dataclass.
    request_json    TEXT NOT NULL,
    -- "daily" | "weekly" | "monthly"
    cadence         TEXT NOT NULL CHECK (cadence IN ('daily','weekly','monthly')),
    -- Hour of day (UTC) at which to fire. 0..23.
    hour_utc        INTEGER NOT NULL DEFAULT 13 CHECK (hour_utc BETWEEN 0 AND 23),
    -- Weekly: 0=Mon..6=Sun. Ignored for daily/monthly.
    day_of_week     INTEGER CHECK (day_of_week BETWEEN 0 AND 6),
    -- Monthly: 1..28 (capped to keep every month valid). Ignored otherwise.
    day_of_month    INTEGER CHECK (day_of_month BETWEEN 1 AND 28),
    -- Optional explicit recipient. NULL = fall back to users.email at run-time.
    email_to        TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    -- Computed by the scheduler on save and after each run, so the loop's
    -- "is anything due?" tick is a single index lookup.
    next_run_at     DATETIME,
    last_run_at     DATETIME,
    -- FK to the reports row produced by the most recent run, if any.
    -- ON DELETE SET NULL so deleting a report doesn't cascade-delete the
    -- schedule (which would lose the user's recurrence config).
    last_report_id  INTEGER REFERENCES reports(id) ON DELETE SET NULL,
    -- Most recent error message, NULL if last run succeeded (or never ran).
    last_error      TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_report_schedules_user
    ON report_schedules(user_id);

-- The scheduler scans this every minute looking for rows where
-- active=1 AND next_run_at <= now(). Partial index keeps the scan tiny.
CREATE INDEX IF NOT EXISTS idx_report_schedules_due
    ON report_schedules(next_run_at)
    WHERE active = 1;

INSERT OR REPLACE INTO schema_version(version) VALUES (5);
