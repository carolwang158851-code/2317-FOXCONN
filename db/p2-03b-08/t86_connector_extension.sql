-- P1008 P2-03B-08 staging-only TWSE T86 connector extension.
-- Do not place in db/migrations without separate Owner approval.

CREATE TABLE connector_contracts (
    connector_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    source_authority TEXT NOT NULL CHECK(source_authority = 'A1'),
    evidence_level TEXT NOT NULL CHECK(evidence_level = 'L1'),
    endpoint_url TEXT NOT NULL,
    official_page_url TEXT NOT NULL,
    endpoint_path TEXT NOT NULL,
    select_type TEXT NOT NULL,
    query_date TEXT NOT NULL CHECK(length(query_date) = 8),
    expected_fields_json TEXT NOT NULL CHECK(json_valid(expected_fields_json)),
    official_unit TEXT NOT NULL CHECK(official_unit = 'SHARES'),
    parser_version TEXT NOT NULL,
    license_scope TEXT NOT NULL,
    fallback_policy TEXT NOT NULL CHECK(fallback_policy = 'NO_FALLBACK'),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE_DRY_RUN','SUSPENDED')),
    owner_approval TEXT NOT NULL
) STRICT;

CREATE TABLE connector_executions (
    execution_uid TEXT PRIMARY KEY CHECK(length(execution_uid) = 26),
    connector_id TEXT NOT NULL REFERENCES connector_contracts(connector_id),
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT NOT NULL CHECK(substr(finished_at, -1) = 'Z'),
    http_status INTEGER,
    mime_type TEXT,
    page_raw_sha256 TEXT CHECK(page_raw_sha256 IS NULL OR length(page_raw_sha256) = 64),
    data_raw_sha256 TEXT CHECK(data_raw_sha256 IS NULL OR length(data_raw_sha256) = 64),
    response_count INTEGER,
    selected_count INTEGER,
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    error_code TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE observation_evidence (
    evidence_uid TEXT PRIMARY KEY CHECK(length(evidence_uid) = 26),
    evidence_id TEXT NOT NULL UNIQUE,
    observation_uid TEXT NOT NULL REFERENCES observations(observation_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256) = 64),
    source_code_value TEXT NOT NULL,
    source_date_value TEXT NOT NULL,
    source_field_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK(validation_status IN ('PASS','PASS_WITH_WARNINGS')),
    model_usage TEXT NOT NULL CHECK(model_usage = 'OBSERVATION_ONLY'),
    warnings_json TEXT NOT NULL CHECK(json_valid(warnings_json)),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

PRAGMA user_version = 8;
