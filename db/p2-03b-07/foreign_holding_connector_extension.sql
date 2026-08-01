-- P1008 P2-03B-07 staging-only TWSE foreign/mainland holding extension.
-- Do not place in db/migrations without separate Owner approval.

CREATE TABLE connector_contracts (
    connector_id TEXT PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    source_authority TEXT NOT NULL CHECK(source_authority = 'A1'),
    evidence_level TEXT NOT NULL CHECK(evidence_level = 'L1'),
    endpoint_url TEXT NOT NULL,
    select_type TEXT NOT NULL CHECK(select_type = 'ALLBUT0999'),
    expected_fields_json TEXT NOT NULL CHECK(json_valid(expected_fields_json)),
    parser_version TEXT NOT NULL,
    fallback_policy TEXT NOT NULL CHECK(fallback_policy = 'NO_SOURCE_FALLBACK'),
    owner_approval TEXT NOT NULL,
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE connector_executions (
    execution_uid TEXT PRIMARY KEY CHECK(length(execution_uid) = 26),
    connector_id TEXT NOT NULL REFERENCES connector_contracts(connector_id),
    started_at TEXT NOT NULL CHECK(substr(started_at, -1) = 'Z'),
    finished_at TEXT NOT NULL CHECK(substr(finished_at, -1) = 'Z'),
    requested_quarter_count INTEGER NOT NULL CHECK(requested_quarter_count = 22),
    successful_snapshot_count INTEGER NOT NULL CHECK(successful_snapshot_count = 22),
    candidate_row_count INTEGER NOT NULL CHECK(candidate_row_count = 21),
    status_code TEXT NOT NULL,
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used = 0),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE foreign_holding_snapshots (
    snapshot_uid TEXT PRIMARY KEY CHECK(length(snapshot_uid) = 26),
    artifact_uid TEXT NOT NULL REFERENCES raw_artifacts(artifact_uid),
    subject_uid TEXT NOT NULL REFERENCES subjects(subject_uid),
    requested_quarter TEXT NOT NULL UNIQUE,
    requested_quarter_end TEXT NOT NULL,
    official_as_of_date TEXT NOT NULL,
    date_alignment_status TEXT NOT NULL CHECK(date_alignment_status IN (
        'EXACT_QUARTER_END', 'PRIOR_AVAILABLE_DATE'
    )),
    company_code TEXT NOT NULL CHECK(company_code = '2317'),
    isin TEXT NOT NULL CHECK(isin = 'TW0002317005'),
    issued_shares TEXT NOT NULL,
    available_investment_shares TEXT NOT NULL,
    foreign_mainland_holding_shares TEXT NOT NULL,
    available_investment_ratio_pct TEXT NOT NULL,
    foreign_mainland_holding_ratio_pct TEXT NOT NULL,
    recomputed_ratio_pct TEXT NOT NULL,
    recompute_difference_pct TEXT NOT NULL,
    common_legal_limit_pct TEXT NOT NULL,
    mainland_legal_limit_pct TEXT NOT NULL,
    change_reason_raw TEXT NOT NULL,
    latest_company_report_date_raw TEXT NOT NULL,
    notes_text TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_row_sha256) = 64),
    validation_status TEXT NOT NULL CHECK(validation_status = 'PASS_WITH_WARNINGS'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE foreign_holding_series (
    series_uid TEXT PRIMARY KEY CHECK(length(series_uid) = 26),
    snapshot_uid TEXT NOT NULL REFERENCES foreign_holding_snapshots(snapshot_uid),
    quarter TEXT NOT NULL UNIQUE,
    ratio_pct TEXT NOT NULL,
    prior_ratio_pct TEXT NOT NULL,
    change_pct_point TEXT NOT NULL,
    trend TEXT NOT NULL CHECK(trend IN ('RISING', 'STABLE', 'DECLINING')),
    is_candidate_row INTEGER NOT NULL CHECK(is_candidate_row IN (0, 1)),
    promotion_status TEXT NOT NULL CHECK(promotion_status = 'CANDIDATE_PENDING_OWNER'),
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

CREATE TABLE candidate_changes (
    change_uid TEXT PRIMARY KEY CHECK(length(change_uid) = 26),
    quarter TEXT NOT NULL,
    field_name TEXT NOT NULL CHECK(field_name IN (
        'ForeignHoldRatio_Pct', 'ForeignHoldChange_Pct', 'ForeignHoldTrend'
    )),
    before_value TEXT NOT NULL,
    after_value TEXT NOT NULL,
    changed INTEGER NOT NULL CHECK(changed IN (0, 1)),
    source_authority TEXT NOT NULL CHECK(source_authority = 'A1'),
    evidence_level TEXT NOT NULL CHECK(evidence_level = 'L1'),
    status_zh TEXT NOT NULL,
    message_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    UNIQUE(quarter, field_name)
) STRICT;

CREATE TABLE candidate_releases (
    release_uid TEXT PRIMARY KEY CHECK(length(release_uid) = 26),
    release_id TEXT NOT NULL UNIQUE,
    manifest_sha256 TEXT NOT NULL UNIQUE CHECK(length(manifest_sha256) = 64),
    candidate_master_sha256 TEXT NOT NULL CHECK(length(candidate_master_sha256) = 64),
    candidate_authority_manifest_sha256 TEXT NOT NULL CHECK(length(candidate_authority_manifest_sha256) = 64),
    status TEXT NOT NULL CHECK(status = 'READY_FOR_OWNER_REVIEW'),
    status_zh TEXT NOT NULL,
    status_note_zh TEXT NOT NULL,
    created_at TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    actionable INTEGER NOT NULL DEFAULT 0 CHECK(actionable = 0)
) STRICT;

PRAGMA user_version = 9;
