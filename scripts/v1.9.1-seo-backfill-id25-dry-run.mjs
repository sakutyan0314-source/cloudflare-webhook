import { createHash } from "node:crypto";

export const TARGET_ID = 25;
export const TARGET_CATEGORY = "saas-cloud";
export const MIN_BODY_LENGTH = 240;
export const SIMILARITY_THRESHOLD = 0.8;
export const READ_ONLY_SQL = "SELECT id, content, created_at, title, description, body_markdown, category, published_at, updated_at, seo_status FROM curation_logs WHERE id=25";

const forbiddenSql = /\b(UPDATE|INSERT|DELETE|ALTER|DROP|REPLACE|CREATE|BEGIN|COMMIT|ROLLBACK)\b/i;
const allowedCategories = new Set(["ai-automation", "saas-cloud", "security-governance", "engineering-infrastructure", "dx-organization", "marketing-cx", "uncategorized"]);

export function sha256(value) {
  return createHash("sha256").update(String(value), "utf8").digest("hex");
}

function isUnset(value) {
  return value === null || value === undefined;
}

function validText(value, minimum, maximum) {
  return typeof value === "string" && value.trim().length >= minimum && value.trim().length <= maximum;
}

export function assertReadOnlySql(sql = READ_ONLY_SQL) {
  if (forbiddenSql.test(sql) || !/^SELECT\b/i.test(sql.trim()) || /;\s*\S/.test(sql)) {
    throw new Error("ID 25 dry-run SQL must be one SELECT-only statement");
  }
  return sql;
}

export function validateManifest(manifest) {
  const entry = manifest?.articles?.[0];
  const errors = [];
  if (!Array.isArray(manifest?.target_ids) || manifest.target_ids.length !== 1 || manifest.target_ids[0] !== TARGET_ID) errors.push("target_ids must be exactly [25]");
  if (!entry || entry.id !== TARGET_ID || manifest.articles.length !== 1) errors.push("manifest must contain exactly ID 25 once");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(manifest?.effective_at || "")) errors.push("effective_at is invalid");
  if (!entry) return errors;
  if (entry.expected?.seo_status !== "legacy") errors.push("expected seo_status must be legacy");
  if (entry.expected?.category !== "uncategorized") errors.push("expected category must be uncategorized");
  for (const key of ["title", "description", "body_markdown", "published_at", "updated_at"]) {
    if (!isUnset(entry.expected?.[key])) errors.push(`expected ${key} must be unset`);
  }
  if (!/^[a-f0-9]{64}$/.test(entry.expected?.content_sha256 || "")) errors.push("expected content SHA-256 is invalid");
  if (!validText(entry.target?.title, 12, 120)) errors.push("target title is invalid");
  if (!validText(entry.target?.description, 60, 160)) errors.push("target description is invalid");
  if (entry.target?.category !== TARGET_CATEGORY || !allowedCategories.has(entry.target?.category)) errors.push("target category must be saas-cloud");
  if (entry.target?.seo_status !== "ready") errors.push("target seo_status must be ready");
  if (entry.target?.updated_at !== manifest.effective_at) errors.push("target updated_at must equal fixed effective_at");
  if (entry.target?.body_markdown_sha256 !== entry.expected?.content_sha256) errors.push("planned body_markdown must equal content by SHA-256");
  if (Number.isNaN(Date.parse(entry.target?.published_at || ""))) errors.push("target published_at is invalid");
  return errors;
}

export function buildDryRunAudit({ manifest, d1Payload, similarTitleIds = [] }) {
  assertReadOnlySql();
  const errors = validateManifest(manifest);
  const result = Array.isArray(d1Payload) ? d1Payload[0] : d1Payload;
  if (!result?.success || !Array.isArray(result.results) || !result.meta) throw new Error("ID 25 dry-run D1 result is invalid");
  const row = result.results[0];
  if (result.results.length !== 1 || row?.id !== TARGET_ID) errors.push("D1 result must contain only ID 25");
  const entry = manifest.articles[0];
  const checks = [];
  if (row) {
    if (row.seo_status !== entry.expected.seo_status) checks.push("seo_status mismatch");
    if (row.category !== entry.expected.category) checks.push("category mismatch");
    for (const key of ["title", "description", "body_markdown", "published_at", "updated_at"]) if (!isUnset(row[key])) checks.push(`${key} must be unset`);
    const contentHash = sha256(row.content);
    if (contentHash !== entry.expected.content_sha256) checks.push("content SHA-256 mismatch");
    if (contentHash !== entry.target.body_markdown_sha256) checks.push("planned body_markdown SHA-256 mismatch");
    if (row.created_at !== entry.target.published_at) checks.push("created_at does not equal approved published_at");
    if (typeof row.content !== "string" || row.content.length < MIN_BODY_LENGTH) checks.push("body is shorter than 240 characters");
    if (!/^#\s+\S/m.test(row.content || "")) checks.push("body has no H1 structure");
    if (!/^##\s+\S/m.test(row.content || "")) checks.push("body has no H2 structure");
    if (similarTitleIds.length > 0) checks.push("recent title similarity is at or above threshold");
  }
  if (result.meta.changed_db !== false) errors.push("D1 meta changed_db must be false");
  if (result.meta.rows_written !== 0) errors.push("D1 meta rows_written must be 0");
  if (checks.length > 0) errors.push("ID 25 failed validation");
  return {
    schema_version: 1,
    mode: "dry-run",
    effective_at: manifest.effective_at,
    target_ids: [TARGET_ID],
    result: errors.length === 0 ? "pass" : "fail",
    errors,
    article: {
      id: TARGET_ID,
      result: checks.length === 0 ? "pass" : "fail",
      checks,
      current: row ? { title: row.title, description: row.description, body_markdown: row.body_markdown, category: row.category, published_at: row.published_at, updated_at: row.updated_at, seo_status: row.seo_status, content_sha256: sha256(row.content) } : null,
      planned: { ...entry.target },
      similarity_peer_ids_at_or_above_threshold: [...similarTitleIds],
    },
    db_write_check: { changed_db: result.meta.changed_db, rows_written: result.meta.rows_written },
  };
}
