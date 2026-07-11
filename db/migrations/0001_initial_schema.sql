-- P1008 Phase 2 / P2-01 initial schema.
-- Forward-only migration. Do not edit after it has been applied.

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL CHECK(length(checksum_sha256) = 64),
    applied_at TEXT NOT NULL CHECK(substr(applied_at, -1) = 'Z'),
    execution_ms INTEGER NOT NULL CHECK(execution_ms >= 0),
    runner_version TEXT NOT NULL
) STRICT;

CREATE TABLE migration_runs (
    run_uid TEXT PRIMARY KEY CHECK(length(run_uid) = 26),
    migration_version INTEGER,
    migration_name TEXT,
    checksum_sha256 TEXT CHECK(checksum_sha256 IS NULL OR length(checksum_sha256) = 64),
    mode TEXT NOT NULL CHECK(mode IN ('DRY_RUN', 'APPLY')),
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'PASS', 'FAIL')),
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT CHECK(finished_at IS NULL OR substr(finished_at, -1) = 'Z'),
    backup_id TEXT,
    message_zh TEXT NOT NULL
) STRICT;

CREATE TABLE pipeline_runs (
    pipeline_run_uid TEXT PRIMARY KEY CHECK(length(pipeline_run_uid) = 26),
    writer_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    heartbeat_at TEXT NOT NULL CHECK(substr(heartbeat_at, -1) = 'Z'),
    lease_expires_at TEXT NOT NULL CHECK(substr(lease_expires_at, -1) = 'Z'),
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETED', 'FAILED', 'ABANDONED')),
    takeover_from_uid TEXT REFERENCES pipeline_runs(pipeline_run_uid),
    message_zh TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX ux_pipeline_runs_single_active
ON pipeline_runs((1))
WHERE status = 'RUNNING';

CREATE TABLE audit_logs (
    audit_uid TEXT PRIMARY KEY CHECK(length(audit_uid) = 26),
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_uid TEXT,
    occurred_at TEXT NOT NULL CHECK(substr(occurred_at, -1) = 'Z'),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL
) STRICT;

CREATE INDEX ix_audit_logs_event_time
ON audit_logs(event_type, occurred_at);

CREATE TABLE backup_records (
    backup_id TEXT PRIMARY KEY,
    database_sha256 TEXT NOT NULL CHECK(length(database_sha256) = 64),
    schema_version INTEGER NOT NULL CHECK(schema_version >= 0),
    latest_observation_at TEXT,
    latest_release_id TEXT,
    backup_reason TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    integrity_check_status TEXT NOT NULL CHECK(integrity_check_status IN ('PASS', 'FAIL')),
    foreign_key_check_status TEXT NOT NULL CHECK(foreign_key_check_status IN ('PASS', 'FAIL')),
    source_database_path TEXT NOT NULL,
    backup_path TEXT NOT NULL UNIQUE,
    manifest_path TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE subjects (
    subject_uid TEXT PRIMARY KEY CHECK(length(subject_uid) = 26),
    subject_type TEXT NOT NULL CHECK(subject_type IN (
        'COMPANY', 'SECURITY', 'FUND', 'FUND_SHARE_CLASS', 'MACRO', 'INDEX'
    )),
    canonical_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    ticker TEXT,
    market TEXT,
    isin TEXT,
    cik TEXT,
    currency TEXT,
    parent_subject_uid TEXT REFERENCES subjects(subject_uid),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'INACTIVE', 'SUPERSEDED')),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    updated_at TEXT NOT NULL CHECK(substr(updated_at, -1) = 'Z')
) STRICT;

CREATE UNIQUE INDEX ux_subjects_isin
ON subjects(isin)
WHERE isin IS NOT NULL;

CREATE INDEX ix_subjects_ticker_market
ON subjects(ticker, market);

CREATE TABLE metric_definitions (
    metric_uid TEXT PRIMARY KEY CHECK(length(metric_uid) = 26),
    metric_code TEXT NOT NULL UNIQUE,
    name_zh TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK(frequency IN (
        'INTRADAY', 'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUAL', 'EVENT'
    )),
    value_type TEXT NOT NULL CHECK(value_type IN (
        'DECIMAL', 'TEXT', 'INTEGER', 'BOOLEAN', 'DATE', 'DATETIME', 'JSON'
    )),
    canonical_unit TEXT,
    is_derived INTEGER NOT NULL CHECK(is_derived IN (0, 1)),
    formula_version TEXT,
    required_for_report INTEGER NOT NULL CHECK(required_for_report IN (0, 1)),
    model_usage TEXT NOT NULL CHECK(model_usage IN (
        'BLOCKED', 'OBSERVATION_ONLY', 'EVIDENCE_ALLOWED'
    )),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    updated_at TEXT NOT NULL CHECK(substr(updated_at, -1) = 'Z'),
    CHECK(
        (is_derived = 0 AND formula_version IS NULL)
        OR (is_derived = 1 AND formula_version IS NOT NULL)
    )
) STRICT;

CREATE TABLE sources (
    source_uid TEXT PRIMARY KEY CHECK(length(source_uid) = 26),
    source_code TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    official_url TEXT,
    quality_level TEXT NOT NULL CHECK(quality_level IN ('A1', 'A2', 'A3', 'A4')),
    license_scope TEXT NOT NULL,
    retrieval_method TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    updated_at TEXT NOT NULL CHECK(substr(updated_at, -1) = 'Z')
) STRICT;

CREATE TABLE raw_artifacts (
    artifact_uid TEXT PRIMARY KEY CHECK(length(artifact_uid) = 26),
    source_uid TEXT NOT NULL REFERENCES sources(source_uid),
    retrieved_at TEXT NOT NULL CHECK(substr(retrieved_at, -1) = 'Z'),
    source_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
    http_status INTEGER,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE INDEX ix_raw_artifacts_source_retrieved
ON raw_artifacts(source_uid, retrieved_at);

CREATE TABLE observations (
    observation_uid TEXT PRIMARY KEY CHECK(length(observation_uid) = 26),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    metric_uid TEXT NOT NULL REFERENCES metric_definitions(metric_uid),
    value_decimal TEXT,
    value_text TEXT,
    unit TEXT,
    period_start TEXT,
    period_end TEXT NOT NULL,
    published_at TEXT NOT NULL CHECK(substr(published_at, -1) = 'Z'),
    effective_at TEXT NOT NULL CHECK(substr(effective_at, -1) = 'Z'),
    retrieved_at TEXT NOT NULL CHECK(substr(retrieved_at, -1) = 'Z'),
    source_uid TEXT NOT NULL REFERENCES sources(source_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS', 'PASS_WITH_WARNINGS', 'CONFLICT', 'FAIL', 'SUPERSEDED'
    )),
    support_level TEXT NOT NULL CHECK(support_level IN ('L1', 'L2', 'L3', 'L4')),
    supersedes_observation_uid TEXT REFERENCES observations(observation_uid),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    CHECK((value_decimal IS NOT NULL) + (value_text IS NOT NULL) = 1),
    CHECK(effective_at >= published_at),
    CHECK(retrieved_at >= published_at)
) STRICT;

CREATE INDEX ix_observations_as_of
ON observations(subject_uid, metric_uid, effective_at, published_at);

CREATE INDEX ix_observations_period_revision
ON observations(subject_uid, metric_uid, period_end, revision);

CREATE TABLE derived_metrics (
    derived_uid TEXT PRIMARY KEY CHECK(length(derived_uid) = 26),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    metric_uid TEXT NOT NULL REFERENCES metric_definitions(metric_uid),
    value_decimal TEXT NOT NULL,
    as_of TEXT NOT NULL CHECK(substr(as_of, -1) = 'Z'),
    formula_id TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    calculated_at TEXT NOT NULL CHECK(substr(calculated_at, -1) = 'Z'),
    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS', 'PASS_WITH_WARNINGS', 'CONFLICT', 'FAIL', 'SUPERSEDED'
    )),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE INDEX ix_derived_metrics_as_of
ON derived_metrics(subject_uid, metric_uid, as_of);

CREATE TABLE derived_metric_inputs (
    derived_uid TEXT NOT NULL REFERENCES derived_metrics(derived_uid) ON DELETE RESTRICT,
    input_position INTEGER NOT NULL CHECK(input_position >= 1),
    input_type TEXT NOT NULL CHECK(input_type IN ('OBSERVATION', 'DERIVED')),
    observation_uid TEXT REFERENCES observations(observation_uid),
    input_derived_uid TEXT REFERENCES derived_metrics(derived_uid),
    PRIMARY KEY(derived_uid, input_position),
    CHECK(
        (input_type = 'OBSERVATION' AND observation_uid IS NOT NULL AND input_derived_uid IS NULL)
        OR
        (input_type = 'DERIVED' AND observation_uid IS NULL AND input_derived_uid IS NOT NULL)
    ),
    CHECK(input_derived_uid IS NULL OR input_derived_uid <> derived_uid)
) STRICT;

CREATE TABLE validation_results (
    validation_uid TEXT PRIMARY KEY CHECK(length(validation_uid) = 26),
    target_type TEXT NOT NULL,
    target_uid TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'BLOCKING')),
    status TEXT NOT NULL CHECK(status IN (
        'PASS', 'PASS_WITH_WARNINGS', 'CONFLICT', 'FAIL', 'SUPERSEDED'
    )),
    message_zh TEXT NOT NULL,
    checked_at TEXT NOT NULL CHECK(substr(checked_at, -1) = 'Z'),
    validator_version TEXT NOT NULL
) STRICT;

CREATE INDEX ix_validation_results_target
ON validation_results(target_type, target_uid, checked_at);

CREATE TABLE data_conflicts (
    conflict_uid TEXT PRIMARY KEY CHECK(length(conflict_uid) = 26),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    metric_uid TEXT NOT NULL REFERENCES metric_definitions(metric_uid),
    period_end TEXT NOT NULL,
    candidate_observation_uids TEXT NOT NULL CHECK(json_valid(candidate_observation_uids)),
    difference TEXT,
    tolerance TEXT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN (
        'OPEN', 'OWNER_REVIEW', 'RESOLVED', 'REJECTED'
    )),
    owner_resolution TEXT,
    resolved_at TEXT CHECK(resolved_at IS NULL OR substr(resolved_at, -1) = 'Z'),
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    CHECK(
        (resolution_status IN ('OPEN', 'OWNER_REVIEW') AND resolved_at IS NULL)
        OR
        (resolution_status IN ('RESOLVED', 'REJECTED') AND resolved_at IS NOT NULL)
    )
) STRICT;

CREATE INDEX ix_data_conflicts_open
ON data_conflicts(subject_uid, metric_uid, period_end)
WHERE resolution_status IN ('OPEN', 'OWNER_REVIEW');

CREATE TABLE data_conflict_candidates (
    conflict_uid TEXT NOT NULL REFERENCES data_conflicts(conflict_uid) ON DELETE RESTRICT,
    observation_uid TEXT NOT NULL REFERENCES observations(observation_uid) ON DELETE RESTRICT,
    PRIMARY KEY(conflict_uid, observation_uid)
) STRICT;

PRAGMA user_version = 1;

