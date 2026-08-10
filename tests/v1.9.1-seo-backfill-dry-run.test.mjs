import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { buildDryRunAudit, READ_ONLY_SQL, sha256, validateManifest } from "../scripts/v1.9.1-seo-backfill-dry-run.mjs";

const manifest = JSON.parse(await fs.readFile(new URL("../ops/v1.9.1-seo-ready-manifest.json", import.meta.url), "utf8"));
const effectiveAt = "2026-08-10T12:30:00.000Z";
const content = (id) => `# Article ${id}\n\n## Core section\n\n${"SEO safe body. ".repeat(30)}`;

function record(entry) {
  return {
    id: entry.id,
    content: content(entry.id),
    created_at: entry.target.published_at,
    title: null,
    description: null,
    body_markdown: null,
    category: "uncategorized",
    published_at: null,
    updated_at: null,
    seo_status: "legacy"
  };
}

function testManifest() {
  return structuredClone(manifest).articles.map((entry) => ({ ...entry, expected: { ...entry.expected, content_sha256: sha256(content(entry.id)) }, target: { ...entry.target } }));
}

function payload(rows, meta = { changed_db: false, rows_written: 0 }) {
  return [{ success: true, results: rows, meta }];
}

function audit({ articles = testManifest(), rows = articles.map(record), meta } = {}) {
  return buildDryRunAudit({ manifest: { ...manifest, articles }, d1Payload: payload(rows, meta), effectiveAt, now: "2026-08-10T12:00:00.000Z" });
}

let count = 0;
async function test(name, fn) {
  await fn();
  count += 1;
  console.log(`ok ${count} - ${name}`);
}

await test("normal three targets pass with read-only metadata", () => {
  const result = audit();
  assert.equal(result.result, "pass");
  assert.equal(result.db_write_check.changed_db, false);
  assert.equal(result.db_write_check.rows_written, 0);
  assert.equal(result.articles.length, 3);
  assert.ok(result.articles.every((article) => article.planned.body_markdown_sha256 === article.content_sha256));
});

await test("missing target fails", () => assert.equal(audit({ rows: testManifest().slice(1).map(record) }).result, "fail"));
await test("out-of-manifest id is rejected", () => {
  const rows = testManifest().map(record);
  rows.push({ ...rows[0], id: 99 });
  assert.match(audit({ rows }).errors.join("\n"), /out-of-manifest/);
});
await test("status mismatch fails", () => {
  const rows = testManifest().map(record); rows[0].seo_status = "ready";
  assert.match(audit({ rows }).articles[0].checks.join("\n"), /seo_status/);
});
await test("set SEO column fails", () => {
  const rows = testManifest().map(record); rows[0].title = "already set";
  assert.match(audit({ rows }).articles[0].checks.join("\n"), /title must be unset/);
});
await test("content SHA mismatch fails", () => {
  const rows = testManifest().map(record); rows[0].content = `${rows[0].content} changed`;
  assert.match(audit({ rows }).articles[0].checks.join("\n"), /SHA-256/);
});
await test("category mismatch fails", () => {
  const rows = testManifest().map(record); rows[0].category = "ai-automation";
  assert.match(audit({ rows }).articles[0].checks.join("\n"), /category/);
});
await test("invalid title and description are rejected", () => {
  const articles = testManifest(); articles[0].target.title = "short"; articles[0].target.description = "too short";
  assert.match(audit({ articles }).errors.join("\n"), /title is invalid/);
  assert.match(audit({ articles }).errors.join("\n"), /description is invalid/);
});
await test("short body and missing H2 fail", () => {
  const rows = testManifest().map(record); rows[0].content = "short";
  const checks = audit({ rows }).articles[0].checks.join("\n");
  assert.match(checks, /shorter than 240/); assert.match(checks, /no H2/);
});
await test("write metadata is rejected", () => {
  const result = audit({ meta: { changed_db: true, rows_written: 1 } });
  assert.match(result.errors.join("\n"), /changed_db/); assert.match(result.errors.join("\n"), /rows_written/);
});
await test("manifest rejects IDs outside the approved trio", () => {
  const invalid = structuredClone(manifest); invalid.target_ids = [17, 20, 99];
  assert.match(validateManifest(invalid).join("\n"), /exactly/);
});
await test("dry-run source has no D1 mutation method or mutation SQL", async () => {
  const source = await fs.readFile(new URL("../scripts/v1.9.1-seo-backfill-dry-run.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\.run\(|\.batch\(|\.exec\(/);
  assert.equal(READ_ONLY_SQL.match(/\b(UPDATE|INSERT|DELETE|ALTER|DROP)\b/gi), null);
});

console.log(`1..${count}`);
