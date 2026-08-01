-- P1008 P2-03B-02 staging-only income statement connector extension.
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
    observation_count INTEGER NOT NULL DEFAULT 0 CHECK(observation_count >= 0),
    blocked_fact_count INTEGER NOT NULL DEFAULT 0 CHECK(blocked_fact_count >= 0),
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    error_code TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE financial_statement_rows (
    statement_row_uid TEXT PRIMARY KEY CHECK(length(statement_row_uid) = 26),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    company_code TEXT NOT NULL CHECK(company_code = '2317'),
    source_report_date TEXT NOT NULL,
    fiscal_year_roc TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER NOT NULL CHECK(fiscal_quarter BETWEEN 1 AND 4),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    period_basis TEXT NOT NULL CHECK(period_basis = 'CUMULATIVE_YTD'),
    reporting_scope_status TEXT NOT NULL CHECK(reporting_scope_status = 'UNVERIFIED'),
    source_row_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_row_sha256) = 64),
    raw_row_json TEXT NOT NULL CHECK(json_valid(raw_row_json)),
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE financial_statement_facts (
    fact_uid TEXT PRIMARY KEY CHECK(length(fact_uid) = 26),
    statement_row_uid TEXT NOT NULL REFERENCES financial_statement_rows(statement_row_uid),
    evidence_id TEXT NOT NULL UNIQUE,
    source_field TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    unit_code TEXT,
    unit_status TEXT NOT NULL CHECK(unit_status IN ('VERIFIED', 'UNVERIFIED')),
    period_basis TEXT NOT NULL CHECK(period_basis = 'CUMULATIVE_YTD'),
    promotion_status TEXT NOT NULL CHECK(promotion_status IN (
        'OBSERVATION_ONLY', 'BLOCKED_UNIT_UNVERIFIED'
    )),
    observation_uid TEXT REFERENCES observations(observation_uid),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    CHECK(
        (promotion_status = 'OBSERVATION_ONLY'
            AND unit_status = 'VERIFIED'
            AND observation_uid IS NOT NULL)
        OR
        (promotion_status = 'BLOCKED_UNIT_UNVERIFIED'
            AND unit_status = 'UNVERIFIED'
            AND observation_uid IS NULL)
    )
) STRICT;

CREATE TABLE observation_evidence (
    evidence_uid TEXT PRIMARY KEY CHECK(length(evidence_uid) = 26),
    evidence_id TEXT NOT NULL UNIQUE,
    observation_uid TEXT NOT NULL REFERENCES observations(observation_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256) = 64),
    source_code_value TEXT NOT NULL,
    source_period_value TEXT NOT NULL,
    source_field TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    model_usage TEXT NOT NULL CHECK(model_usage = 'OBSERVATION_ONLY'),
    warnings_json TEXT NOT NULL CHECK(json_valid(warnings_json)),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

PRAGMA user_version = 5;
