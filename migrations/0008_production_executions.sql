-- Durable, metadata-only single-use execution state for approved canaries.
-- This does not connect to the Worker or authorize publication.  Existing
-- cron/manual pipeline runs, QualityGateAudit rows, and article data remain
-- untouched.  Forward-only migration; do not edit after release.

CREATE TABLE production_executions (
  production_execution_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'approved-canary-production-execution-v1'),
  production_input_id TEXT NOT NULL UNIQUE,
  production_input_fingerprint TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  topic_candidate_id TEXT NOT NULL,
  human_review_id TEXT NOT NULL,
  trigger_type TEXT NOT NULL CHECK (trigger_type = 'approved_canary'),
  state TEXT NOT NULL CHECK (state IN ('planned', 'preflight_verified', 'approval_verified', 'send_started', 'outcome_known_success', 'outcome_known_failed', 'outcome_unknown')),
  classification TEXT CHECK (classification IN ('success', 'known_failure', 'outcome_unknown', 'pre_send_resume_candidate')),
  state_version INTEGER NOT NULL CHECK (state_version >= 0),
  started_at TEXT,
  send_started_at TEXT,
  completed_at TEXT,
  pipeline_run_id INTEGER,
  final_article_id INTEGER,
  quality_gate_audit_id TEXT,
  notification_classification TEXT NOT NULL DEFAULT 'not_applicable' CHECK (notification_classification IN ('not_applicable', 'not_started', 'sent', 'failed', 'delivery_unknown')),
  publication_authorized INTEGER NOT NULL DEFAULT 0 CHECK (publication_authorized = 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id) ON DELETE RESTRICT,
  FOREIGN KEY (final_article_id) REFERENCES curation_logs(id) ON DELETE RESTRICT,
  FOREIGN KEY (quality_gate_audit_id) REFERENCES quality_gate_audits(audit_id) ON DELETE RESTRICT
);

CREATE INDEX idx_production_executions_state_created
  ON production_executions (state, created_at DESC);
CREATE INDEX idx_production_executions_pipeline_run
  ON production_executions (pipeline_run_id)
  WHERE pipeline_run_id IS NOT NULL;
CREATE INDEX idx_production_executions_quality_gate_audit
  ON production_executions (quality_gate_audit_id)
  WHERE quality_gate_audit_id IS NOT NULL;

CREATE TABLE production_execution_events (
  event_id TEXT PRIMARY KEY,
  production_execution_id TEXT NOT NULL,
  event_sequence INTEGER NOT NULL CHECK (event_sequence >= 0),
  from_state TEXT CHECK (from_state IN ('planned', 'preflight_verified', 'approval_verified', 'send_started', 'outcome_known_success', 'outcome_known_failed', 'outcome_unknown')),
  to_state TEXT NOT NULL CHECK (to_state IN ('planned', 'preflight_verified', 'approval_verified', 'send_started', 'outcome_known_success', 'outcome_known_failed', 'outcome_unknown')),
  classification TEXT CHECK (classification IN ('success', 'known_failure', 'outcome_unknown', 'pre_send_resume_candidate')),
  reason_code TEXT CHECK (reason_code IN ('approval_expired', 'approval_mismatch', 'production_input_mismatch', 'candidate_fingerprint_mismatch', 'review_chain_invalid', 'superseded_review', 'routing_invalid', 'legacy_dependency', 'duplicate_execution', 'canary_not_allowed', 'transport_known_failure', 'transport_timeout', 'transport_connection_failure', 'response_malformed', 'process_interrupted', 'outcome_unknown_requires_review', 'state_transition_conflict', 'pipeline_run_link_failed', 'publication_not_authorized')),
  occurred_at TEXT NOT NULL,
  UNIQUE (production_execution_id, event_sequence),
  FOREIGN KEY (production_execution_id) REFERENCES production_executions(production_execution_id) ON DELETE RESTRICT
);

CREATE INDEX idx_production_execution_events_execution_sequence
  ON production_execution_events (production_execution_id, event_sequence);
CREATE INDEX idx_production_execution_events_reason_occurred
  ON production_execution_events (reason_code, occurred_at DESC)
  WHERE reason_code IS NOT NULL;
