-- P1008 P2-03B-03 staging-only balance sheet connector extension.
-- Do not place in db/migrations without separate Owner approval.

CREATE TABLE connector_contracts (
    connector_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    source_authority TEXT NOT NULL CHECK(source_authority = 'A1'),
    evidence_level TEXT NOT NULL CHECK(evidence_level = 'L1'),
    endpoint_url TEXT NOT NULL,
    swagger_url TEXT NOT NULL,
    swagger_sha256 TEXT NOT NULL CHECK(length(swagger_sha256) = 64),
    endpoint_path TEXT NOT NULL,
    expected_fields_json TEXT NOT NULL CHECK(json_valid(expected_fields_json)),
    actual_top_level_shape TEXT NOT NULL,
    documented_top_level_shape TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    license_scope TEXT NOT NULL,
    fallback_policy TEXT NOT NULL CHECK(fallback_policy = 'NO_FALLBACK'),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE_DRY_RUN', 'SUSPENDED')),
    owner_approval TEXT NOT NULL
) STRICT;

CREATE TABLE connector_executions (
    execution_uid TEXT PRIMARY KEY CHECK(length(execution_uid) = 26),
    connector_id TEXT NOT NULL REFERENCES connector_contracts(connector_id),
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT NOT NULL CHECK(substr(finished_at, -1) = 'Z'),
    http_status INTEGER,
    mime_type TEXT,
    raw_sha256 TEXT CHECK(raw_sha256 IS NULL OR length(raw_sha256) = 64),
    response_count INTEGER,
    selected_count INTEGER,
    fact_count INTEGER NOT NULL DEFAULT 0 CHECK(fact_count >= 0),
    observation_count INTEGER NOT NULL DEFAULT 0 CHECK(observation_count = 0),
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    error_code TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE balance_sheet_rows (
    balance_sheet_row_uid TEXT PRIMARY KEY CHECK(length(balance_sheet_row_uid) = 26),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    company_code TEXT NOT NULL CHECK(company_code = '2317'),
    source_report_date TEXT NOT NULL,
    fiscal_year_roc TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER NOT NULL CHECK(fiscal_quarter BETWEEN 1 AND 4),
    period_end TEXT NOT NULL,
    reporting_scope_status TEXT NOT NULL CHECK(reporting_scope_status = 'UNVERIFIED'),
    source_row_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_row_sha256) = 64),
    raw_row_json TEXT NOT NULL CHECK(json_valid(raw_row_json)),
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE balance_sheet_facts (
    fact_uid TEXT PRIMARY KEY CHECK(length(fact_uid) = 26),
    balance_sheet_row_uid TEXT NOT NULL REFERENCES balance_sheet_rows(balance_sheet_row_uid),
    evidence_id TEXT NOT NULL UNIQUE,
    source_field TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    unit_code TEXT,
    unit_status TEXT NOT NULL CHECK(unit_status = 'UNVERIFIED'),
    promotion_status TEXT NOT NULL CHECK(promotion_status = 'BLOCKED_UNIT_SCOPE_UNVERIFIED'),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE source_comparisons (
    comparison_uid TEXT PRIMARY KEY CHECK(length(comparison_uid) = 26),
    fact_uid TEXT NOT NULL REFERENCES balance_sheet_facts(fact_uid),
    comparison_code TEXT NOT NULL UNIQUE,
    source_metric_code TEXT NOT NULL,
    source_value TEXT NOT NULL,
    existing_dataset_path TEXT NOT NULL,
    existing_metric_code TEXT NOT NULL,
    existing_value TEXT NOT NULL,
    difference TEXT NOT NULL,
    comparison_status TEXT NOT NULL CHECK(comparison_status IN (
        'SOURCE_MATCH_CONFIRMED', 'DATA_CONFLICT_PENDING'
    )),
    promotion_allowed INTEGER NOT NULL DEFAULT 0 CHECK(promotion_allowed = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

PRAGMA user_version = 6;
