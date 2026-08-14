import assert from "node:assert/strict";
import fs from "node:fs";
import { buildDryRunAudit, READ_ONLY_SQL, TARGET_ID, assertReadOnlySql, sha256, validateManifest } from "../scripts/v1.9.1-seo-backfill-id25-dry-run.mjs";

const manifest = JSON.parse(fs.readFileSync(new URL("../ops/v1.9.1-seo-ready-id25-manifest.json", import.meta.url), "utf8"));
const content = "# テスト記事タイトル\n\n## 要点\n\n" + "本文です。".repeat(100);
const row = { id: 25, content, created_at: "2026-08-08T23:02:08.448Z", title: null, description: null, body_markdown: null, category: "uncategorized", published_at: null, updated_at: null, seo_status: "legacy" };
const localManifest = structuredClone(manifest);
localManifest.articles[0].expected.content_sha256 = sha256(content);
localManifest.articles[0].target.body_markdown_sha256 = sha256(content);

function payload(values = [row], meta = { changed_db: false, rows_written: 0 }) {
  return { success: true, results: values, meta };
}

assert.equal(TARGET_ID, 25);
assert.match(READ_ONLY_SQL, /^SELECT\b/i);
assertReadOnlySql();
assert.deepEqual(validateManifest(localManifest), []);

const pass = buildDryRunAudit({ manifest: localManifest, d1Payload: payload() });
assert.equal(pass.result, "pass");
assert.equal(pass.article.planned.updated_at, "2026-08-14T19:07:44.000Z");
assert.equal(pass.article.current.content_sha256, pass.article.planned.body_markdown_sha256);

for (const mutate of [
  (item) => { item.results = []; },
  (item) => { item.results = [{ ...row, id: 26 }]; },
  (item) => { item.results = [{ ...row, category: "saas-cloud" }]; },
  (item) => { item.results = [{ ...row, content: "# 短い\n\n本文" }]; },
  (item) => { item.meta = { changed_db: true, rows_written: 0 }; },
]) {
  const candidate = payload(); mutate(candidate);
  assert.equal(buildDryRunAudit({ manifest: localManifest, d1Payload: candidate }).result, "fail");
}

assert.equal(buildDryRunAudit({ manifest: localManifest, d1Payload: payload(), similarTitleIds: [24] }).result, "fail");
assert.throws(() => assertReadOnlySql("UPDATE curation_logs SET seo_status='ready'"));
console.log("v1.9.1 ID 25 dry-run tests passed");
