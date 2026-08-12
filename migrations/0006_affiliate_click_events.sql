-- Record first-party Amazon affiliate click events without storing requester PII.
-- This migration does not alter article content, pipeline, Discord state, or Search Console data.

CREATE TABLE affiliate_click_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  article_id INTEGER NOT NULL,
  link_type TEXT NOT NULL CHECK (link_type IN ('amazon_search')),
  placement TEXT NOT NULL CHECK (placement IN ('article', 'discord')),
  category TEXT NOT NULL CHECK (category IN (
    'ai-automation',
    'saas-cloud',
    'security-governance',
    'engineering-infrastructure',
    'dx-organization',
    'marketing-cx',
    'uncategorized'
  )),
  clicked_at TEXT NOT NULL,
  FOREIGN KEY (article_id) REFERENCES curation_logs(id) ON DELETE RESTRICT
);

CREATE INDEX idx_affiliate_click_events_article_clicked_at
  ON affiliate_click_events (article_id, clicked_at DESC);

CREATE INDEX idx_affiliate_click_events_placement_clicked_at
  ON affiliate_click_events (placement, clicked_at DESC);
