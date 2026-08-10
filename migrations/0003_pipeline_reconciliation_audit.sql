-- Add a durable, content-free audit trail for human reconciliation decisions.
-- No existing run or article is changed by this migration.
-- Rollback is a reviewed forward migration; do not edit after release.

CREATE TABLE pipeline_reconciliation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_key TEXT NOT NULL UNIQUE,
  pipeline_run_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  previous_status TEXT NOT NULL,
  previous_notification_status TEXT NOT NULL,
  resulting_status TEXT NOT NULL,
  resulting_notification_status TEXT NOT NULL,
  evidence_summary TEXT NOT NULL,
  actor_type TEXT NOT NULL DEFAULT 'authenticated_operator',
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX idx_pipeline_reconciliation_events_run_created
  ON pipeline_reconciliation_events (pipeline_run_id, created_at DESC);
