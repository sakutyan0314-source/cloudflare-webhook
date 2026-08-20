import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("../src/index.ts", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const worker = (await import(moduleUrl)).default;

const rows = [
  {
    id: 17, source_type: "test", llm_name: "test", created_at: "2026-08-02T23:02:06.682Z",
    content: "# 自律駆動型\n\n## 要点\n\n本文です。", title: "自律駆動型エンタープライズ", description: "AIと自動化による企業変革について解説する記事です。",
    body_markdown: "## 要点\n\n本文です。", category: "ai-automation", published_at: "2026-08-02T23:02:06.682Z", updated_at: "2026-08-10T15:27:33.000Z", seo_status: "ready"
  },
  {
    id: 20, source_type: "test", llm_name: "test", created_at: "2026-08-04T23:01:39.914Z",
    content: "# SaaSの変化\n\n## 要点\n\n本文です。", title: "SaaSの変化", description: "SaaSと組織運営の変化について解説する記事です。",
    body_markdown: "## 要点\n\n本文です。", category: "saas-cloud", published_at: "2026-08-04T23:01:39.914Z", updated_at: "2026-08-10T15:27:33.000Z", seo_status: "ready"
  },
  {
    id: 26, source_type: "test", llm_name: "test", created_at: "2026-08-09T20:40:17.892Z",
    content: "# Agentic Mesh\n\n## 要点\n\n本文です。", title: "Agentic Mesh", description: "自律型エージェント網による企業変革について解説する記事です。",
    body_markdown: "## 要点\n\n本文です。", category: "ai-automation", published_at: "2026-08-09T20:40:17.892Z", updated_at: "2026-08-10T15:27:33.000Z", seo_status: "ready"
  },
  {
    id: 30, source_type: "test", llm_name: "test", created_at: "2026-08-01T00:00:00.000Z",
    content: "# 既存記事\n\n## 要点\n\n本文です。", title: null, description: null, body_markdown: null,
    category: "uncategorized", published_at: null, updated_at: null, seo_status: "legacy"
  },
  {
    id: 31, source_type: "test", llm_name: "test", created_at: "2026-08-11T00:00:00.000Z",
    content: "# 確認待ち\n\n## 要点\n\n本文です。", title: "確認待ち", description: "確認待ちの記事です。", body_markdown: "## 要点\n\n本文です。",
    category: "ai-automation", published_at: "2026-08-11T00:00:00.000Z", updated_at: "2026-08-11T00:00:00.000Z", seo_status: "needs_review"
  }
];

const env = {
  SITE_URL: "https://cloudflare-webhook.tyansaku3325.workers.dev",
  AMAZON_TAG: "test-22",
  DB: {
    prepare(sql) {
      const statement = {
        args: [],
        bind(...args) { this.args = args; return this; },
        async first() { return rows.find((row) => row.id === Number(this.args[0])) ?? null; },
        async all() { return { results: rows }; }
      };
      return statement;
    }
  }
};

let count = 0;
async function test(name, fn) {
  await fn();
  count += 1;
  console.log(`ok ${count} - ${name}`);
}

await test("category page exposes only its public category articles with breadcrumbs", async () => {
  const response = await worker.fetch(new Request("https://local.test/category/ai-automation"), env, {});
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(html, /canonical" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/ai-automation"/);
  assert.match(html, /自律駆動型エンタープライズ/);
  assert.match(html, /Agentic Mesh/);
  assert.doesNotMatch(html, /確認待ち/);
  assert.doesNotMatch(html, /SaaSの変化/);
  assert.match(html, /BreadcrumbList/);
});

await test("empty and uncategorized category routes are non-public", async () => {
  for (const slug of ["uncategorized", "marketing-cx"]) {
    const response = await worker.fetch(new Request(`https://local.test/category/${slug}`), env, {});
    assert.equal(response.status, 404);
    assert.equal(response.headers.get("X-Robots-Tag"), "noindex");
  }
});

await test("home links only public category labels to their existing category pages", async () => {
  const response = await worker.fetch(new Request("https://local.test/"), env, {});
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(html, /<a class="category" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/ai-automation">AI・自動化<\/a>/);
  assert.match(html, /<a class="category" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/saas-cloud">SaaS・クラウド<\/a>/);
  assert.match(html, /<span class="category">その他<\/span>/);
  assert.doesNotMatch(html, /category\/uncategorized/);
  assert.doesNotMatch(html, /確認待ち/);
  assert.match(html, /href="\/article\/17">自律駆動型エンタープライズ<\/a>/);
});

await test("ready article has category breadcrumb, BreadcrumbList, and same-category related link", async () => {
  const response = await worker.fetch(new Request("https://local.test/article/17"), env, {});
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(html, /href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/ai-automation"/);
  assert.match(html, /BreadcrumbList/);
  assert.match(html, /関連記事/);
  assert.match(html, /href="\/article\/26">Agentic Mesh/);
  assert.doesNotMatch(html, /href="\/article\/17">自律駆動型エンタープライズ/);
  assert.doesNotMatch(html, /確認待ち/);
});

await test("single-item category omits related module and legacy omits uncategorized breadcrumb", async () => {
  const ready = await worker.fetch(new Request("https://local.test/article/20"), env, {});
  assert.doesNotMatch(await ready.text(), /関連記事/);
  const legacy = await worker.fetch(new Request("https://local.test/article/30"), env, {});
  const legacyHtml = await legacy.text();
  assert.equal(legacy.status, 200);
  assert.doesNotMatch(legacyHtml, /category\/uncategorized/);
});

await test("sitemap adds only non-empty editorial category URLs with max updated_at", async () => {
  const response = await worker.fetch(new Request("https://local.test/sitemap.xml"), env, {});
  const xml = await response.text();
  assert.equal(response.status, 200);
  assert.match(xml, /<loc>https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/ai-automation<\/loc>\n    <lastmod>2026-08-10T15:27:33\.000Z<\/lastmod>/);
  assert.match(xml, /<loc>https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/category\/saas-cloud<\/loc>/);
  assert.doesNotMatch(xml, /category\/uncategorized|category\/marketing-cx|article\/31/);
});

console.log(`1..${count}`);
