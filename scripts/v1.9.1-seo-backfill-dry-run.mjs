import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const TARGET_IDS = Object.freeze([17, 20, 26]);
export const ALLOWED_CATEGORIES = new Set([
  "ai-automation", "saas-cloud", "security-governance",
  "engineering-infrastructure", "dx-organization", "marketing-cx", "uncategorized"
]);
export const READ_ONLY_SQL = `SELECT id, content, created_at, title, description, body_markdown, category, published_at, updated_at, seo_status FROM curation_logs WHERE id IN (17, 20, 26) ORDER BY id ASC`;

const forbiddenSql = /\b(UPDATE|INSERT|DELETE|ALTER|DROP|REPLACE|CREATE|BEGIN|COMMIT|ROLLBACK)\b/i;

export function sha256(value) {
  return createHash("sha256").update(String(value), "utf8").digest("hex");
}

export function validateEffectiveAt(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) || Number.isNaN(Date.parse(value))) {
    throw new Error("--effective-at must be a fixed ISO-8601 UTC timestamp with milliseconds");
  }
  return value;
}

export function assertReadOnlySql(sql = READ_ONLY_SQL) {
  if (forbiddenSql.test(sql) || !/^SELECT\b/i.test(sql.trim())) throw new Error("Dry-run SQL must be SELECT-only");
  return sql;
}

function isUnset(value) {
  return value === null || value === undefined;
}

function validText(value, minimum, maximum) {
  return typeof value === "string" && value.trim().length >= minimum && value.trim().length <= maximum;
}

export function validateManifest(manifest) {
  const errors = [];
  const ids = manifest?.target_ids;
  if (!Array.isArray(ids) || ids.length !== TARGET_IDS.length || ids.some((id, index) => id !== TARGET_IDS[index])) {
    errors.push("manifest target_ids must be exactly [17, 20, 26]");
  }
  if (!Array.isArray(manifest?.articles) || manifest.articles.length !== TARGET_IDS.length) {
    errors.push("manifest must contain exactly three articles");
    return errors;
  }
  const seen = new Set();
  for (const article of manifest.articles) {
    if (!TARGET_IDS.includes(article?.id) || seen.has(article.id)) errors.push(`manifest contains invalid or duplicate id ${article?.id}`);
    seen.add(article?.id);
    if (article?.expected?.seo_status !== "legacy") errors.push(`id ${article?.id}: expected seo_status must be legacy`);
    if (article?.expected?.category !== "uncategorized") errors.push(`id ${article?.id}: expected category must be uncategorized`);
    for (const key of ["title", "description", "body_markdown", "published_at", "updated_at"]) {
      if (!isUnset(article?.expected?.[key])) errors.push(`id ${article?.id}: expected ${key} must be unset`);
    }
    if (!/^[a-f0-9]{64}$/.test(article?.expected?.content_sha256 || "")) errors.push(`id ${article?.id}: expected content_sha256 is invalid`);
    if (!validText(article?.target?.title, 12, 120)) errors.push(`id ${article?.id}: target title is invalid`);
    if (!validText(article?.target?.description, 60, 160)) errors.push(`id ${article?.id}: target description is invalid`);
    if (!ALLOWED_CATEGORIES.has(article?.target?.category) || article.target.category === "uncategorized") errors.push(`id ${article?.id}: target category is invalid`);
    if (article?.target?.seo_status !== "ready") errors.push(`id ${article?.id}: target seo_status must be ready`);
    if (article?.target?.published_at !== undefined && Number.isNaN(Date.parse(article.target.published_at))) errors.push(`id ${article?.id}: target published_at is invalid`);
  }
  return errors;
}

export function extractD1Result(payload) {
  const result = Array.isArray(payload) ? payload[0] : payload;
  if (!result?.success || !Array.isArray(result.results) || !result.meta) throw new Error("Invalid D1 SELECT result");
  return result;
}

export function buildDryRunAudit({ manifest, d1Payload, effectiveAt, now = new Date().toISOString() }) {
  validateEffectiveAt(effectiveAt);
  assertReadOnlySql();
  const errors = validateManifest(manifest);
  const result = extractD1Result(d1Payload);
  const rowsById = new Map(result.results.map((row) => [row.id, row]));
  const articles = [];

  for (const entry of manifest.articles ?? []) {
    const row = rowsById.get(entry.id);
    const checks = [];
    if (!row) {
      checks.push("target row is missing");
    } else {
      if (row.seo_status !== entry.expected.seo_status) checks.push("seo_status mismatch");
      if (row.category !== entry.expected.category) checks.push("category mismatch");
      for (const key of ["title", "description", "body_markdown", "published_at", "updated_at"]) {
        if (!isUnset(row[key])) checks.push(`${key} must be unset`);
      }
      const contentHash = sha256(row.content);
      if (contentHash !== entry.expected.content_sha256) checks.push("content SHA-256 mismatch");
      if (row.created_at !== entry.target.published_at) checks.push("created_at does not equal approved published_at");
      if (typeof row.content !== "string" || row.content.length < 240) checks.push("body is shorter than 240 characters");
      if (!/^##\s+\S/m.test(row.content || "")) checks.push("body has no H2 structure");
      articles.push({
        id: entry.id,
        result: checks.length === 0 ? "pass" : "fail",
        checks,
        content_sha256: contentHash,
        planned: {
          title: entry.target.title,
          description: entry.target.description,
          category: entry.target.category,
          published_at: entry.target.published_at,
          updated_at: effectiveAt,
          seo_status: entry.target.seo_status,
          body_markdown_sha256: contentHash
        }
      });
    }
  }
  for (const id of rowsById.keys()) if (!TARGET_IDS.includes(id)) errors.push(`D1 result contains out-of-manifest id ${id}`);
  if (rowsById.size !== TARGET_IDS.length) errors.push("D1 result must contain exactly three target rows");
  if (result.meta.changed_db !== false) errors.push("D1 meta changed_db must be false");
  if (result.meta.rows_written !== 0) errors.push("D1 meta rows_written must be 0");
  if (articles.some((article) => article.result !== "pass")) errors.push("one or more target articles failed validation");

  return {
    schema_version: 1,
    mode: "dry-run",
    generated_at: now,
    effective_at: effectiveAt,
    target_ids: TARGET_IDS,
    select_sql_sha256: sha256(READ_ONLY_SQL),
    manifest_sha256: sha256(JSON.stringify(manifest)),
    result: errors.length === 0 ? "pass" : "fail",
    errors,
    articles,
    db_write_check: { changed_db: result.meta.changed_db, rows_written: result.meta.rows_written }
  };
}

export async function writeAuditBundle({ manifestPath, manifest, audit, auditDir }) {
  const resolvedDir = path.resolve(auditDir);
  const workspace = process.cwd() + path.sep;
  if (!path.isAbsolute(auditDir) || resolvedDir.startsWith(workspace)) throw new Error("--audit-dir must be an absolute path outside the repository");
  await fs.mkdir(resolvedDir, { recursive: true, mode: 0o700 });
  const stamp = audit.generated_at.replace(/[:.]/g, "-");
  const manifestCopy = path.join(resolvedDir, `${stamp}_manifest.json`);
  const auditFile = path.join(resolvedDir, `${stamp}_dry-run.json`);
  const manifestText = await fs.readFile(manifestPath, "utf8");
  const auditText = `${JSON.stringify(audit, null, 2)}\n`;
  await fs.writeFile(manifestCopy, manifestText, { mode: 0o600 });
  await fs.writeFile(`${manifestCopy}.sha256`, `${sha256(manifestText)}  ${path.basename(manifestCopy)}\n`, { mode: 0o600 });
  await fs.writeFile(auditFile, auditText, { mode: 0o600 });
  await fs.writeFile(`${auditFile}.sha256`, `${sha256(auditText)}  ${path.basename(auditFile)}\n`, { mode: 0o600 });
  return { manifestCopy, auditFile };
}

export function runRemoteSelect() {
  assertReadOnlySql();
  const output = execFileSync("npx", ["wrangler", "d1", "execute", "zero-capital-insight-db", "--remote", "--config", "./wrangler.toml", "--command", READ_ONLY_SQL, "--json"], { encoding: "utf8" });
  return JSON.parse(output);
}

function parseArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (!key?.startsWith("--") || value === undefined) throw new Error("Usage: --effective-at <ISO> --audit-dir <absolute-external-path> [--input <d1-json>]");
    options[key.slice(2)] = value;
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options["effective-at"] || !options["audit-dir"]) throw new Error("--effective-at and --audit-dir are required");
  const manifestPath = path.resolve("ops/v1.9.1-seo-ready-manifest.json");
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  const d1Payload = options.input ? JSON.parse(await fs.readFile(options.input, "utf8")) : runRemoteSelect();
  const audit = buildDryRunAudit({ manifest, d1Payload, effectiveAt: options["effective-at"] });
  const files = await writeAuditBundle({ manifestPath, manifest, audit, auditDir: options["audit-dir"] });
  console.log(JSON.stringify({ result: audit.result, audit: files, errors: audit.errors }, null, 2));
  if (audit.result !== "pass") process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
