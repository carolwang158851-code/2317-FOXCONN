-- P1008 P2-03B-06 staging-only MOPS Inline XBRL cash flow extension.
-- Do not place in db/migrations without separate Owner approval.

CREATE TABLE connector_contracts (
    connector_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    source_authority TEXT NOT NULL CHECK(source_authority = 'A1'),
    evidence_level TEXT NOT NULL CHECK(evidence_level = 'L1'),
    discovery_url TEXT NOT NULL,
    download_url TEXT NOT NULL,
    manual_verification_url TEXT NOT NULL,
    expected_concepts_json TEXT NOT NULL CHECK(json_valid(expected_concepts_json)),
    taxonomy_namespaces_json TEXT NOT NULL CHECK(json_valid(taxonomy_namespaces_json)),
    schema_ref TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    license_scope TEXT NOT NULL,
    fallback_policy TEXT NOT NULL CHECK(fallback_policy = 'NO_SOURCE_FALLBACK'),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE_DRY_RUN', 'SUSPENDED')),
    owner_approval TEXT NOT NULL
) STRICT;

CREATE TABLE connector_executions (
    execution_uid TEXT PRIMARY KEY CHECK(length(execution_uid) = 26),
    connector_id TEXT NOT NULL REFERENCES connector_contracts(connector_id),
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT NOT NULL CHECK(substr(finished_at, -1) = 'Z'),
    discovery_http_status INTEGER,
    xbrl_http_status INTEGER,
    manual_http_status INTEGER,
    xbrl_sha256 TEXT NOT NULL CHECK(length(xbrl_sha256) = 64),
    fact_count INTEGER NOT NULL CHECK(fact_count = 8),
    observation_count INTEGER NOT NULL CHECK(observation_count = 8),
    blocked_fact_count INTEGER NOT NULL DEFAULT 0 CHECK(blocked_fact_count = 0),
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE xbrl_reports (
    report_uid TEXT PRIMARY KEY CHECK(length(report_uid) = 26),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    company_code TEXT NOT NULL CHECK(company_code = '2317'),
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER NOT NULL CHECK(fiscal_quarter BETWEEN 1 AND 4),
    report_category TEXT NOT NULL CHECK(report_category = 'Consolidated report'),
    report_scope TEXT NOT NULL CHECK(report_scope = 'CONSOLIDATED'),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    schema_ref TEXT NOT NULL,
    namespaces_json TEXT NOT NULL CHECK(json_valid(namespaces_json)),
    context_count INTEGER NOT NULL CHECK(context_count > 0),
    unit_count INTEGER NOT NULL CHECK(unit_count > 0),
    source_report_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_report_sha256) = 64),
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE xbrl_cash_flow_facts (
    fact_uid TEXT PRIMARY KEY CHECK(length(fact_uid) = 26),
    report_uid TEXT NOT NULL REFERENCES xbrl_reports(report_uid),
    evidence_id TEXT NOT NULL UNIQUE,
    concept_qname TEXT NOT NULL,
    metric_code TEXT NOT NULL UNIQUE,
    context_ref TEXT NOT NULL,
    period_scope TEXT NOT NULL CHECK(period_scope IN ('CUMULATIVE_YTD', 'INSTANT')),
    raw_display_value TEXT NOT NULL,
    normalized_value_twd TEXT NOT NULL,
    unit_ref TEXT NOT NULL CHECK(unit_ref = 'TWD'),
    unit_measure TEXT NOT NULL CHECK(unit_measure = 'iso4217:TWD'),
    scale_value INTEGER NOT NULL,
    decimals_value TEXT NOT NULL,
    sign_value TEXT,
    promotion_status TEXT NOT NULL CHECK(promotion_status = 'OBSERVATION_ONLY'),
    observation_uid TEXT NOT NULL REFERENCES observations(observation_uid),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE observation_evidence (
    evidence_uid TEXT PRIMARY KEY CHECK(length(evidence_uid) = 26),
    evidence_id TEXT NOT NULL UNIQUE,
    observation_uid TEXT NOT NULL REFERENCES observations(observation_uid),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    concept_qname TEXT NOT NULL,
    context_ref TEXT NOT NULL,
    unit_ref TEXT NOT NULL,
    raw_display_value TEXT NOT NULL,
    normalized_value_twd TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    model_usage TEXT NOT NULL CHECK(model_usage = 'OBSERVATION_ONLY'),
    warnings_json TEXT NOT NULL CHECK(json_valid(warnings_json)),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

CREATE TABLE source_comparisons (
    comparison_uid TEXT PRIMARY KEY CHECK(length(comparison_uid) = 26),
    comparison_code TEXT NOT NULL UNIQUE,
    related_fact_uids_json TEXT NOT NULL CHECK(json_valid(related_fact_uids_json)),
    source_value TEXT NOT NULL,
    source_unit TEXT NOT NULL,
    existing_dataset_path TEXT NOT NULL,
    existing_metric_code TEXT NOT NULL,
    existing_value TEXT NOT NULL,
    difference TEXT NOT NULL,
    tolerance TEXT NOT NULL,
    comparison_status TEXT NOT NULL CHECK(comparison_status IN (
        'SOURCE_MATCH_CONFIRMED', 'DATA_CONFLICT_PENDING', 'FORMULA_NOT_APPROVED'
    )),
    promotion_allowed INTEGER NOT NULL DEFAULT 0 CHECK(promotion_allowed = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z')
) STRICT;

PRAGMA user_version = 8;
