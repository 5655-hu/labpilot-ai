-- LabPilot AI schema (SQLite compatible — keep every statement valid in
-- plain SQLite AND in Turso libSQL, so production can switch by DATABASE_URL
-- without a migration. No Postgres-only syntax here.)
-- Version: 1 (Wave 1)

CREATE TABLE IF NOT EXISTS datasets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    file_hash   TEXT NOT NULL,          -- SHA-256 of the stored parsed file
    rows_count  INTEGER NOT NULL,
    cols_count  INTEGER NOT NULL,
    columns_json TEXT NOT NULL,         -- ["col1", "col2", ...] + dtypes
    source      TEXT NOT NULL DEFAULT 'upload',  -- 'upload' | 'golden'
    file_path   TEXT,                   -- local parsed file; production moves this to Turso/object storage
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id  INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    params_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,                   -- structured analysis JSON (Wave 2+)
    engine_version TEXT NOT NULL DEFAULT '0.1.0',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_analyses_dataset ON analyses(dataset_id);
CREATE INDEX IF NOT EXISTS idx_datasets_created ON datasets(created_at);
