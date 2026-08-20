-- Durable, metadata-only state for separately approved SEO snippet execution.
-- This migration does not modify existing tables or execute article updates.

CREATE TABLE seo_execution_attempts (
  execution_attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'seo-improvement-execution-attempt-v1'),
  execution_approval_id TEXT NOT NULL UNIQUE,
  preflight_id TEXT NOT NULL UNIQUE,
  execution_candidate_id TEXT NOT NULL,
  execution_candidate_fingerprint TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_fingerprint TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  proposal_fingerprint TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  plan_fingerprint TEXT NOT NULL,
  article_id INTEGER NOT NULL,
  before_snapshot_fingerprint TEXT NOT NULL,
  after_snapshot_fingerprint TEXT NOT NULL,
  expected_diff_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('planned', 'approval_reserved', 'update_started', 'outcome_known_success', 'outcome_known_failure', 'outcome_unknown')),
  classification TEXT NOT NULL CHECK (classification IN ('not_started', 'approval_reserved', 'update_started', 'success', 'known_failure', 'outcome_unknown')),
  state_version INTEGER NOT NULL CHECK (state_version >= 0),
  started_at TEXT NOT NULL,
  update_started_at TEXT,
  completed_at TEXT,
  changed_db INTEGER CHECK (changed_db IN (0, 1) OR changed_db IS NULL),
  changes INTEGER CHECK (changes IS NULL OR changes >= 0),
  returned_article_id INTEGER,
  execution_authorized INTEGER NOT NULL DEFAULT 0 CHECK (execution_authorized = 0),
  publication_authorized INTEGER NOT NULL DEFAULT 0 CHECK (publication_authorized = 0),
  created_at TEXT NOT NULL
);

CREATE INDEX idx_seo_execution_attempts_state_created
  ON seo_execution_attempts (state, created_at DESC);

CREATE TABLE seo_execution_attempt_events (
  event_id TEXT NOT NULL UNIQUE,
  execution_attempt_id TEXT NOT NULL,
  event_sequence INTEGER NOT NULL CHECK (event_sequence >= 0),
  from_state TEXT CHECK (from_state IN ('planned', 'approval_reserved', 'update_started', 'outcome_known_success', 'outcome_known_failure', 'outcome_unknown')),
  to_state TEXT NOT NULL CHECK (to_state IN ('planned', 'approval_reserved', 'update_started', 'outcome_known_success', 'outcome_known_failure', 'outcome_unknown')),
  classification TEXT NOT NULL CHECK (classification IN ('not_started', 'approval_reserved', 'update_started', 'success', 'known_failure', 'outcome_unknown')),
  reason_code TEXT CHECK (reason_code IN ('approval_expired', 'approval_already_reserved', 'preflight_identity_mismatch', 'stale_snapshot', 'conditional_update_no_match', 'conditional_update_returning_mismatch', 'transaction_failed', 'outcome_unknown')),
  occurred_at TEXT NOT NULL,
  PRIMARY KEY (execution_attempt_id, event_sequence),
  FOREIGN KEY (execution_attempt_id) REFERENCES seo_execution_attempts(execution_attempt_id) ON DELETE RESTRICT
);

CREATE TRIGGER seo_execution_attempt_events_no_update
BEFORE UPDATE ON seo_execution_attempt_events
BEGIN SELECT RAISE(ABORT, 'seo_execution_attempt_events_append_only'); END;
CREATE TRIGGER seo_execution_attempt_events_no_delete
BEFORE DELETE ON seo_execution_attempt_events
BEGIN SELECT RAISE(ABORT, 'seo_execution_attempt_events_append_only'); END;

CREATE TABLE seo_execution_post_verifications (
  post_verification_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'seo-improvement-execution-post-verification-v1'),
  execution_attempt_id TEXT NOT NULL UNIQUE,
  article_id INTEGER NOT NULL,
  after_snapshot_fingerprint TEXT NOT NULL,
  observed_snapshot_fingerprint TEXT NOT NULL,
  expected_diff_json TEXT NOT NULL,
  title_description_match INTEGER NOT NULL CHECK (title_description_match IN (0, 1)),
  forbidden_fields_unchanged INTEGER NOT NULL CHECK (forbidden_fields_unchanged IN (0, 1)),
  content_hash_unchanged INTEGER NOT NULL CHECK (content_hash_unchanged IN (0, 1)),
  body_markdown_hash_unchanged INTEGER NOT NULL CHECK (body_markdown_hash_unchanged IN (0, 1)),
  classification TEXT NOT NULL CHECK (classification IN ('pass', 'fail')),
  created_at TEXT NOT NULL,
  FOREIGN KEY (execution_attempt_id) REFERENCES seo_execution_attempts(execution_attempt_id) ON DELETE RESTRICT
);
