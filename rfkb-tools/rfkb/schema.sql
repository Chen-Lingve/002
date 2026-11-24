PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL,
    test_only INTEGER NOT NULL CHECK(test_only IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    rowid INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    version INTEGER NOT NULL CHECK(version > 0),
    status TEXT NOT NULL CHECK(status IN ('draft','pending','published','superseded','retired')),
    title TEXT NOT NULL, summary TEXT NOT NULL, family TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '', variant TEXT NOT NULL DEFAULT '',
    body_json TEXT NOT NULL, references_json TEXT NOT NULL, content_hash TEXT NOT NULL,
    edit_token INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    reviewed_by TEXT, review_note TEXT,
    UNIQUE(record_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_published_revision
ON revisions(record_id) WHERE status = 'published';
CREATE INDEX IF NOT EXISTS revision_filters ON revisions(status, family, role, variant);
CREATE TABLE IF NOT EXISTS dependencies (
    revision_rowid INTEGER NOT NULL REFERENCES revisions(rowid),
    target_record_id TEXT NOT NULL, target_version INTEGER NOT NULL, locator TEXT NOT NULL,
    FOREIGN KEY(target_record_id, target_version) REFERENCES revisions(record_id, version),
    PRIMARY KEY(revision_rowid, target_record_id, target_version)
);
CREATE TABLE IF NOT EXISTS constraints_index (
    revision_rowid INTEGER NOT NULL REFERENCES revisions(rowid),
    semantic_id TEXT NOT NULL, quantity TEXT NOT NULL, unit TEXT NOT NULL,
    lower_value TEXT, upper_value TEXT, note TEXT NOT NULL,
    PRIMARY KEY(revision_rowid, semantic_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS record_search
USING fts5(title, summary, body, tokenize='trigram');
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
    version INTEGER NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
    from_status TEXT, to_status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
    storage_name TEXT NOT NULL UNIQUE, byte_count INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY, request_json TEXT NOT NULL, context_json TEXT NOT NULL,
    result_json TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revision_snapshots (
    record_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, captured_at TEXT NOT NULL, provenance TEXT NOT NULL,
    PRIMARY KEY(record_id, version, content_hash),
    FOREIGN KEY(record_id, version) REFERENCES revisions(record_id, version)
);
CREATE TRIGGER IF NOT EXISTS revision_snapshots_no_update
BEFORE UPDATE ON revision_snapshots BEGIN SELECT RAISE(ABORT, 'Snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS revision_snapshots_no_delete
BEFORE DELETE ON revision_snapshots BEGIN SELECT RAISE(ABORT, 'Snapshots are immutable'); END;
CREATE TABLE IF NOT EXISTS audit_snapshots (
    event_id INTEGER PRIMARY KEY REFERENCES audit_events(id),
    record_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
    FOREIGN KEY(record_id, version, content_hash)
        REFERENCES revision_snapshots(record_id, version, content_hash)
);
CREATE TABLE IF NOT EXISTS legacy_case_classifications (
    record_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
    case_type TEXT NOT NULL CHECK(case_type IN ('project_case', 'general_method')),
    PRIMARY KEY(record_id, version, content_hash),
    FOREIGN KEY(record_id, version) REFERENCES revisions(record_id, version)
);
