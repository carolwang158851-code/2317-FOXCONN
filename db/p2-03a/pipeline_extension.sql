-- P1008 P2-03A staging-only pipeline extension.
-- This file must not be placed in db/migrations until separately approved.

CREATE TABLE connector_registry (
    connector_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    source_authority TEXT NOT NULL CHECK(source_authority IN ('A1','A2','A3','A4')),
    supported_subject_types TEXT NOT NULL CHECK(json_valid(supported_subject_types)),
    supported_metrics TEXT NOT NULL CHECK(json_valid(supported_metrics)),
    parser_version TEXT NOT NULL,
    license_scope TEXT NOT NULL,
    rate_limit TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    health_status TEXT NOT NULL CHECK(health_status IN (
        'HEALTHY','DEGRADED','UNAVAILABLE','DISABLED'
    )),
    is_test_fixture INTEGER NOT NULL CHECK(is_test_fixture = 1)
) STRICT;

CREATE TABLE source_priority_registry (
    registry_uid TEXT PRIMARY KEY CHECK(length(registry_uid) = 26),
    dataset_code TEXT NOT NULL UNIQUE,
    metric_group TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    primary_source_codes TEXT NOT NULL CHECK(json_valid(primary_source_codes)),
    secondary_source_codes TEXT NOT NULL CHECK(json_valid(secondary_source_codes)),
    cross_check_source_codes TEXT NOT NULL CHECK(json_valid(cross_check_source_codes)),
    fallback_policy TEXT NOT NULL CHECK(fallback_policy = 'NO_SILENT_FALLBACK'),
    conflict_policy TEXT NOT NULL,
    license_requirement TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    registry_version TEXT NOT NULL,
    owner_approval TEXT NOT NULL
) STRICT;

CREATE TABLE freshness_policies (
    policy_uid TEXT PRIMARY KEY CHECK(length(policy_uid) = 26),
    dataset_code TEXT NOT NULL UNIQUE,
    metric_group TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    expected_frequency TEXT NOT NULL,
    expected_publish_rule TEXT NOT NULL,
    grace_period_days INTEGER NOT NULL CHECK(grace_period_days >= 0),
    stale_after_days INTEGER NOT NULL CHECK(stale_after_days >= 0),
    severely_stale_after_days INTEGER NOT NULL CHECK(severely_stale_after_days >= stale_after_days),
    calendar_code TEXT NOT NULL,
    timezone TEXT NOT NULL,
    missing_action TEXT NOT NULL,
    version TEXT NOT NULL,
    owner_approval TEXT NOT NULL
) STRICT;

CREATE TABLE connector_runs (
    connector_run_uid TEXT PRIMARY KEY CHECK(length(connector_run_uid) = 26),
    connector_id TEXT NOT NULL REFERENCES connector_registry(connector_id),
    scenario_code TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    artifact_sha256 TEXT CHECK(artifact_sha256 IS NULL OR length(artifact_sha256) = 64),
    error_code TEXT,
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE pipeline_validations (
    pipeline_validation_uid TEXT PRIMARY KEY CHECK(length(pipeline_validation_uid) = 26),
    scenario_code TEXT NOT NULL,
    dataset_code TEXT NOT NULL,
    validation_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','BLOCKING')),
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    checked_at TEXT NOT NULL,
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE pipeline_conflicts (
    pipeline_conflict_uid TEXT PRIMARY KEY CHECK(length(pipeline_conflict_uid) = 26),
    scenario_code TEXT NOT NULL,
    dataset_code TEXT NOT NULL,
    primary_source_code TEXT NOT NULL,
    secondary_source_code TEXT NOT NULL,
    comparison_type TEXT NOT NULL,
    primary_sha256 TEXT NOT NULL CHECK(length(primary_sha256) = 64),
    secondary_sha256 TEXT NOT NULL CHECK(length(secondary_sha256) = 64),
    resolution_status TEXT NOT NULL CHECK(resolution_status IN (
        'DETECTED','UNDER_REVIEW','UNRESOLVED_BLOCKING','RESOLVED'
    )),
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE release_batches (
    release_uid TEXT PRIMARY KEY CHECK(length(release_uid) = 26),
    release_id TEXT NOT NULL UNIQUE,
    as_of TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'DRAFT','VALIDATING','READY_FOR_REVIEW','REJECTED','APPROVED',
        'PUBLISHING','ACTIVE','FAILED','SUPERSEDED','ROLLED_BACK'
    )),
    sqlite_snapshot_sha256 TEXT NOT NULL CHECK(length(sqlite_snapshot_sha256) = 64),
    manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
    created_at TEXT NOT NULL,
    approved_at TEXT,
    published_at TEXT,
    supersedes_release_uid TEXT REFERENCES release_batches(release_uid),
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL
) STRICT;

CREATE TABLE release_items (
    release_item_uid TEXT PRIMARY KEY CHECK(length(release_item_uid) = 26),
    release_uid TEXT NOT NULL REFERENCES release_batches(release_uid),
    dataset_code TEXT NOT NULL,
    candidate_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    column_count INTEGER NOT NULL CHECK(column_count >= 0),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    schema_version TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    changed_rows INTEGER NOT NULL CHECK(changed_rows >= 0),
    UNIQUE(release_uid, dataset_code)
) STRICT;

CREATE TABLE release_approvals (
    approval_uid TEXT PRIMARY KEY CHECK(length(approval_uid) = 26),
    release_uid TEXT NOT NULL REFERENCES release_batches(release_uid),
    manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
    accepted_warning_codes TEXT NOT NULL CHECK(json_valid(accepted_warning_codes)),
    reason TEXT NOT NULL
) STRICT;

CREATE TABLE publication_attempts (
    attempt_uid TEXT PRIMARY KEY CHECK(length(attempt_uid) = 26),
    release_uid TEXT,
    actor_role TEXT NOT NULL,
    manifest_sha256 TEXT,
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    target_root TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

PRAGMA user_version = 3;

