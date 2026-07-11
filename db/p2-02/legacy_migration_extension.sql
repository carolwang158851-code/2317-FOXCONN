-- P1008 P2-02 staging-only extension.
-- This file is not part of the runtime migration directory.

CREATE TABLE legacy_migration_runs (
    legacy_run_uid TEXT PRIMARY KEY CHECK(length(legacy_run_uid) = 26),
    run_id TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT CHECK(finished_at IS NULL OR substr(finished_at, -1) = 'Z'),
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'PASS', 'FAIL')),
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    source_hashes_json TEXT NOT NULL CHECK(json_valid(source_hashes_json)),
    runtime_database_sha256_before TEXT NOT NULL CHECK(length(runtime_database_sha256_before) = 64),
    runtime_database_sha256_after TEXT CHECK(
        runtime_database_sha256_after IS NULL OR length(runtime_database_sha256_after) = 64
    ),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE legacy_source_rows (
    legacy_row_uid TEXT PRIMARY KEY CHECK(length(legacy_row_uid) = 26),
    legacy_run_uid TEXT NOT NULL REFERENCES legacy_migration_runs(legacy_run_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    dataset_code TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_line INTEGER NOT NULL CHECK(source_line >= 1),
    logical_row_number INTEGER NOT NULL CHECK(logical_row_number >= 1),
    row_key TEXT NOT NULL,
    period_key TEXT NOT NULL,
    raw_row_sha256 TEXT NOT NULL CHECK(length(raw_row_sha256) = 64),
    source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
    row_status TEXT NOT NULL CHECK(row_status IN ('VALID', 'EXCLUDED_INVALID')),
    issues_json TEXT NOT NULL CHECK(json_valid(issues_json)),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    UNIQUE(legacy_run_uid, dataset_code, source_line)
) STRICT;

CREATE INDEX ix_legacy_source_rows_dataset_status
ON legacy_source_rows(dataset_code, row_status, source_line);

CREATE TABLE legacy_field_mappings (
    mapping_uid TEXT PRIMARY KEY CHECK(length(mapping_uid) = 26),
    legacy_run_uid TEXT NOT NULL REFERENCES legacy_migration_runs(legacy_run_uid),
    dataset_code TEXT NOT NULL,
    source_column TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL CHECK(source_ordinal >= 1),
    target_kind TEXT NOT NULL CHECK(target_kind IN (
        'CONTEXT', 'METADATA', 'OBSERVATION', 'OBSERVATION_LEGACY_DERIVED',
        'DERIVED_METRIC'
    )),
    metric_uid TEXT REFERENCES metric_definitions(metric_uid),
    metric_code TEXT,
    name_zh TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK(value_type IN ('DECIMAL', 'TEXT', 'DATE')),
    canonical_unit TEXT,
    classification TEXT NOT NULL CHECK(classification IN (
        'TIME_AXIS', 'IDENTITY_CONTEXT', 'GOVERNANCE_METADATA', 'RAW_FACT',
        'NORMALIZED_FACT', 'ESTIMATED_FACT', 'LEGACY_DERIVED', 'LEGACY_INFERENCE'
    )),
    formula_id TEXT,
    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS', 'PASS_WITH_WARNINGS'
    )),
    model_usage TEXT NOT NULL CHECK(model_usage = 'OBSERVATION_ONLY'),
    status_note_zh TEXT NOT NULL,
    UNIQUE(legacy_run_uid, dataset_code, source_column)
) STRICT;

CREATE TABLE evidence_records (
    evidence_uid TEXT PRIMARY KEY CHECK(length(evidence_uid) = 26),
    evidence_id TEXT NOT NULL UNIQUE,
    legacy_run_uid TEXT NOT NULL REFERENCES legacy_migration_runs(legacy_run_uid),
    legacy_row_uid TEXT NOT NULL REFERENCES legacy_source_rows(legacy_row_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    observation_uid TEXT REFERENCES observations(observation_uid),
    derived_uid TEXT REFERENCES derived_metrics(derived_uid),
    source_column TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL CHECK(source_ordinal >= 1),
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    period_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    evidence_hash_sha256 TEXT NOT NULL CHECK(length(evidence_hash_sha256) = 64),
    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS', 'PASS_WITH_WARNINGS'
    )),
    model_usage TEXT NOT NULL CHECK(model_usage = 'OBSERVATION_ONLY'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    CHECK(
        (observation_uid IS NOT NULL AND derived_uid IS NULL)
        OR
        (observation_uid IS NULL AND derived_uid IS NOT NULL)
    )
) STRICT;

CREATE INDEX ix_evidence_records_source
ON evidence_records(artifact_uid, legacy_row_uid, source_column);

CREATE INDEX ix_evidence_records_target_observation
ON evidence_records(observation_uid)
WHERE observation_uid IS NOT NULL;

CREATE INDEX ix_evidence_records_target_derived
ON evidence_records(derived_uid)
WHERE derived_uid IS NOT NULL;

PRAGMA user_version = 2;

