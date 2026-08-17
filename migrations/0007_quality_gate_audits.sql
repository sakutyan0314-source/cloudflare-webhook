-- Append-only, content-free audit records for the existing seo_quality gate.
-- Local implementation only until separately approved for production.

CREATE TABLE quality_gate_audits (
  audit_id TEXT PRIMARY KEY,
  pipeline_run_id INTEGER NOT NULL,
  schema_version TEXT NOT NULL CHECK (schema_version = 'quality-gate-audit-v1'),
  stage TEXT NOT NULL CHECK (stage = 'seo_quality'),
  classification TEXT NOT NULL CHECK (classification IN ('pass', 'fail', 'needs_review', 'input_invalid')),
  threshold_version TEXT NOT NULL CHECK (threshold_version = 'seo_quality_threshold_v1'),
  evaluated_at TEXT NOT NULL,
  UNIQUE (pipeline_run_id, stage),
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id) ON DELETE RESTRICT
);

CREATE TABLE quality_gate_audit_checks (
  audit_id TEXT NOT NULL,
  check_name TEXT NOT NULL CHECK (check_name IN ('h1_structure', 'title_presence', 'body_presence', 'body_length', 'h2_count', 'description_presence', 'category_allowed', 'duplicate_similarity')),
  status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'not_evaluated', 'review_required')),
  observed_value REAL,
  required_min REAL,
  required_max REAL,
  threshold REAL,
  compared_article_count INTEGER CHECK (compared_article_count IS NULL OR compared_article_count >= 0),
  PRIMARY KEY (audit_id, check_name),
  FOREIGN KEY (audit_id) REFERENCES quality_gate_audits(audit_id) ON DELETE RESTRICT
);

CREATE TABLE quality_gate_audit_reasons (
  audit_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK (reason_code IN ('h1_missing_or_invalid', 'title_missing', 'body_missing', 'description_missing', 'category_not_allowed', 'body_length_below_minimum', 'insufficient_h2_count', 'seo_quality_check_failed', 'duplicate_risk_exceeded')),
  reason_order INTEGER NOT NULL CHECK (reason_order >= 0),
  PRIMARY KEY (audit_id, reason_code),
  UNIQUE (audit_id, reason_order),
  FOREIGN KEY (audit_id) REFERENCES quality_gate_audits(audit_id) ON DELETE RESTRICT
);

CREATE INDEX idx_quality_gate_audits_classification_evaluated
  ON quality_gate_audits (classification, evaluated_at DESC);
CREATE INDEX idx_quality_gate_audits_threshold_evaluated
  ON quality_gate_audits (threshold_version, evaluated_at DESC);
CREATE INDEX idx_quality_gate_audit_reasons_code_audit
  ON quality_gate_audit_reasons (reason_code, audit_id);
CREATE INDEX idx_quality_gate_audit_checks_name_status_audit
  ON quality_gate_audit_checks (check_name, status, audit_id);
