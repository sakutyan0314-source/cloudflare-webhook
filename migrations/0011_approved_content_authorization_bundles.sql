-- Immutable, content-free authorization snapshots for approved topic-aware canaries.
-- This table adds no approval decision and does not grant publication authority.

CREATE TABLE approved_content_authorization_bundles (
  authorization_bundle_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = 'approved-content-production-authorization-bundle-v1'),
  topic_candidate_id TEXT NOT NULL,
  review_id TEXT NOT NULL,
  production_input_id TEXT NOT NULL UNIQUE,
  production_approval_id TEXT NOT NULL UNIQUE,
  production_execution_id TEXT NOT NULL UNIQUE,
  cluster_id TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  single_use INTEGER NOT NULL CHECK (single_use = 1),
  candidate_snapshot_json TEXT NOT NULL,
  review_snapshot_json TEXT NOT NULL,
  approved_planning_snapshot_json TEXT NOT NULL,
  content_handoff_snapshot_json TEXT NOT NULL,
  production_input_snapshot_json TEXT NOT NULL,
  approval_snapshot_json TEXT NOT NULL,
  bundle_fingerprint TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  CHECK (expires_at > approved_at)
);

CREATE INDEX idx_approved_content_authorization_bundles_expiry
  ON approved_content_authorization_bundles (expires_at, production_input_id);
