-- Baseline adopted from the production D1 schema observed on 2026-08-10.
-- This is not a reconstruction of the database's original migration history.
-- Before applying to an existing database, verify exact schema equivalence
-- using sqlite_master and the relevant PRAGMA metadata. Stop on any drift.

CREATE TABLE IF NOT EXISTS curation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,
  llm_name TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT NOT NULL,
  target_url TEXT NOT NULL,
  category TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  title TEXT NOT NULL,
  structured_summary TEXT NOT NULL,
  importance_score TEXT NOT NULL,
  deadline_date TEXT,
  status TEXT DEFAULT 'pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS notifications_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  insight_id INTEGER,
  dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL,
  FOREIGN KEY (insight_id) REFERENCES insights(id)
);

CREATE TABLE IF NOT EXISTS sent_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE,
  title TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,
  target_url TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  timestamp TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_articles_created_at
  ON articles (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_insights_created
  ON insights (created_at);

CREATE INDEX IF NOT EXISTS idx_insights_status
  ON insights (status);

CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at
  ON tasks (status, created_at);
