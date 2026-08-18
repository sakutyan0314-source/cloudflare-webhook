-- Approved-canary publication boundary.  Draft content is isolated from all
-- existing public curation_logs queries until a separately approved publish.

CREATE TABLE content_staging_drafts (
  staging_draft_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'content-staging-draft-v1'),
  production_execution_id TEXT NOT NULL UNIQUE,
  production_input_id TEXT NOT NULL,
  topic_candidate_id TEXT NOT NULL,
  quality_gate_audit_id TEXT NOT NULL,
  final_content_fingerprint TEXT NOT NULL,
  fingerprint_schema_version TEXT NOT NULL CHECK (fingerprint_schema_version = 'publication-content-fingerprint-v1'),
  seo_quality_classification TEXT NOT NULL CHECK (seo_quality_classification = 'pass'),
  publication_status TEXT NOT NULL DEFAULT 'publication_pending' CHECK (publication_status IN ('publication_pending', 'rejected', 'published')),
  content TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('ai-automation', 'saas-cloud', 'security-governance', 'engineering-infrastructure', 'dx-organization', 'marketing-cx')),
  seo_status TEXT NOT NULL CHECK (seo_status = 'ready'),
  published_at_candidate TEXT,
  updated_at_candidate TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (production_execution_id) REFERENCES production_executions(production_execution_id) ON DELETE RESTRICT,
  FOREIGN KEY (quality_gate_audit_id) REFERENCES quality_gate_audits(audit_id) ON DELETE RESTRICT
);
CREATE INDEX idx_content_staging_drafts_publication_status_created
  ON content_staging_drafts (publication_status, created_at DESC);
CREATE INDEX idx_content_staging_drafts_quality_gate_audit
  ON content_staging_drafts (quality_gate_audit_id);

CREATE TABLE publication_executions (
  publication_execution_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'approved-canary-publication-execution-v1'),
  staging_draft_id TEXT NOT NULL UNIQUE,
  production_execution_id TEXT NOT NULL UNIQUE,
  publication_approval_id TEXT NOT NULL UNIQUE,
  final_content_fingerprint TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('planned', 'preflight_verified', 'approval_verified', 'publish_started', 'published', 'publication_outcome_unknown')),
  classification TEXT CHECK (classification IN ('published', 'outcome_unknown')),
  state_version INTEGER NOT NULL CHECK (state_version >= 0),
  publish_started_at TEXT,
  completed_at TEXT,
  final_article_id INTEGER,
  notification_classification TEXT NOT NULL DEFAULT 'not_applicable' CHECK (notification_classification IN ('not_applicable', 'eligible', 'sent', 'failed', 'delivery_unknown')),
  created_at TEXT NOT NULL,
  FOREIGN KEY (staging_draft_id) REFERENCES content_staging_drafts(staging_draft_id) ON DELETE RESTRICT,
  FOREIGN KEY (production_execution_id) REFERENCES production_executions(production_execution_id) ON DELETE RESTRICT,
  FOREIGN KEY (final_article_id) REFERENCES curation_logs(id) ON DELETE RESTRICT
);
CREATE INDEX idx_publication_executions_state_created
  ON publication_executions (state, created_at DESC);

CREATE TABLE publication_execution_events (
  event_id TEXT PRIMARY KEY,
  publication_execution_id TEXT NOT NULL,
  event_sequence INTEGER NOT NULL CHECK (event_sequence >= 0),
  from_state TEXT CHECK (from_state IN ('planned', 'preflight_verified', 'approval_verified', 'publish_started', 'published', 'publication_outcome_unknown')),
  to_state TEXT NOT NULL CHECK (to_state IN ('planned', 'preflight_verified', 'approval_verified', 'publish_started', 'published', 'publication_outcome_unknown')),
  classification TEXT CHECK (classification IN ('published', 'outcome_unknown')),
  reason_code TEXT CHECK (reason_code IN ('publication_approval_missing', 'publication_approval_expired', 'publication_approval_mismatch', 'content_fingerprint_mismatch', 'quality_gate_not_passed', 'duplicate_publication', 'concurrent_publication', 'publication_state_conflict', 'curation_insert_failed', 'publication_outcome_unknown', 'notification_not_eligible')),
  occurred_at TEXT NOT NULL,
  UNIQUE (publication_execution_id, event_sequence),
  FOREIGN KEY (publication_execution_id) REFERENCES publication_executions(publication_execution_id) ON DELETE RESTRICT
);
CREATE INDEX idx_publication_execution_events_execution_sequence
  ON publication_execution_events (publication_execution_id, event_sequence);
