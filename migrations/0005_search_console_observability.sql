-- Add an isolated, audited Search Console observation layer.
-- This migration does not modify content, pipeline, reconciliation, or notification data.
-- Collector implementation and any remote application are separate approved operations.

CREATE TABLE search_console_sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT NOT NULL UNIQUE,
  property_uri TEXT NOT NULL,
  search_type TEXT NOT NULL,
  metric_family TEXT NOT NULL CHECK (metric_family IN ('page_daily', 'query_page_daily')),
  sync_kind TEXT NOT NULL CHECK (sync_kind IN ('scheduled', 'refresh', 'manual')),
  metric_start_date TEXT NOT NULL,
  metric_end_date TEXT NOT NULL,
  dimensions_json TEXT NOT NULL,
  row_limit INTEGER NOT NULL CHECK (row_limit BETWEEN 1 AND 25000),
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
  rows_received INTEGER NOT NULL DEFAULT 0 CHECK (rows_received >= 0),
  rows_saved INTEGER NOT NULL DEFAULT 0 CHECK (rows_saved >= 0),
  error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 1000),
  started_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX idx_search_console_sync_runs_status_started_at
  ON search_console_sync_runs (status, started_at DESC);

CREATE TABLE search_console_page_daily_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sync_run_id INTEGER NOT NULL,
  metric_date TEXT NOT NULL,
  property_uri TEXT NOT NULL,
  search_type TEXT NOT NULL,
  page_url TEXT NOT NULL,
  url_kind TEXT NOT NULL CHECK (url_kind IN ('article', 'category', 'top', 'listing', 'unknown')),
  article_id INTEGER,
  clicks INTEGER NOT NULL CHECK (clicks >= 0),
  impressions INTEGER NOT NULL CHECK (impressions >= 0),
  ctr REAL NOT NULL CHECK (ctr >= 0 AND ctr <= 1),
  position REAL NOT NULL CHECK (position >= 0),
  observed_at TEXT NOT NULL,
  UNIQUE (property_uri, search_type, metric_date, page_url),
  FOREIGN KEY (sync_run_id) REFERENCES search_console_sync_runs(id) ON DELETE RESTRICT
);

CREATE INDEX idx_search_console_page_daily_metrics_property_date
  ON search_console_page_daily_metrics (property_uri, search_type, metric_date DESC);

CREATE INDEX idx_search_console_page_daily_metrics_article_date
  ON search_console_page_daily_metrics (article_id, metric_date DESC)
  WHERE article_id IS NOT NULL;

CREATE TABLE search_console_query_page_daily_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sync_run_id INTEGER NOT NULL,
  metric_date TEXT NOT NULL,
  property_uri TEXT NOT NULL,
  search_type TEXT NOT NULL,
  query_text TEXT NOT NULL,
  page_url TEXT NOT NULL,
  url_kind TEXT NOT NULL CHECK (url_kind IN ('article', 'category', 'top', 'listing', 'unknown')),
  article_id INTEGER,
  clicks INTEGER NOT NULL CHECK (clicks >= 0),
  impressions INTEGER NOT NULL CHECK (impressions >= 0),
  ctr REAL NOT NULL CHECK (ctr >= 0 AND ctr <= 1),
  position REAL NOT NULL CHECK (position >= 0),
  observed_at TEXT NOT NULL,
  UNIQUE (property_uri, search_type, metric_date, query_text, page_url),
  FOREIGN KEY (sync_run_id) REFERENCES search_console_sync_runs(id) ON DELETE RESTRICT
);

CREATE INDEX idx_search_console_query_page_daily_metrics_property_date
  ON search_console_query_page_daily_metrics (property_uri, search_type, metric_date DESC);

CREATE INDEX idx_search_console_query_page_daily_metrics_article_date
  ON search_console_query_page_daily_metrics (article_id, metric_date DESC)
  WHERE article_id IS NOT NULL;
