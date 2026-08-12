import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("../src/index.ts", import.meta.url), "utf8");
const moduleSource = `${source}\nexport { buildDiscordMessage };`;
const workerModule = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`);
const worker = workerModule.default;
const { buildDiscordMessage } = workerModule;

const article = {
  id: 17, content: "# AI運用\n\n## 要点\n\nAIと自動化を実務で活用します。",
  created_at: "2026-08-10T00:00:00.000Z", title: "AI運用", description: "AI運用の記事です。",
  body_markdown: "## 要点\n\nAIと自動化を実務で活用します。", category: "ai-automation",
  published_at: "2026-08-10T00:00:00.000Z", updated_at: "2026-08-10T00:00:00.000Z", seo_status: "ready"
};
const hidden = { ...article, id: 18, seo_status: "needs_review" };
const writes = [];
let writeFails = false;

const env = {
  SITE_URL: "https://cloudflare-webhook.tyansaku3325.workers.dev",
  AMAZON_TAG: "test-22",
  DB: {
    prepare(sql) {
      const statement = {
        args: [],
        bind(...args) { this.args = args; return this; },
        async first() { return [article, hidden].find((row) => row.id === Number(this.args[0])) ?? null; },
        async all() { return { results: [article, hidden] }; },
        async run() {
          if (writeFails) throw new Error("D1 unavailable");
          writes.push({ sql, args: this.args });
          return { meta: { changes: 1 } };
        }
      };
      return statement;
    }
  }
};

let count = 0;
async function test(name, fn) { await fn(); count += 1; console.log(`ok ${count} - ${name}`); }

await test("article page uses the first-party measured affiliate link", async () => {
  const response = await worker.fetch(new Request("https://local.test/article/17"), env, {});
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.match(html, /https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/go\/amazon\/17\?placement=article/);
  assert.doesNotMatch(html, /href="https:\/\/www\.amazon\.co\.jp/);
});

await test("valid article click writes one event before a restricted Amazon redirect", async () => {
  writes.length = 0;
  const response = await worker.fetch(new Request("https://local.test/go/amazon/17?placement=article"), env, {});
  assert.equal(response.status, 302);
  assert.match(response.headers.get("Location"), /^https:\/\/www\.amazon\.co\.jp\/s\?/);
  assert.match(response.headers.get("Location"), /tag=test-22/);
  assert.equal(response.headers.get("X-Robots-Tag"), "noindex");
  assert.equal(writes.length, 1);
  assert.match(writes[0].sql, /INSERT INTO affiliate_click_events/);
  assert.deepEqual(writes[0].args.slice(1, 5), [17, "amazon_search", "article", "ai-automation"]);
});

await test("untrusted redirect inputs and hidden articles are rejected without a write", async () => {
  for (const url of [
    "https://local.test/go/amazon/17?placement=external",
    "https://local.test/go/amazon/17?placement=article&url=https://example.test",
    "https://local.test/go/amazon/17?placement=article&tag=override",
    "https://local.test/go/amazon/18?placement=article"
  ]) {
    writes.length = 0;
    const response = await worker.fetch(new Request(url), env, {});
    assert.notEqual(response.status, 302);
    assert.equal(writes.length, 0);
  }
});

await test("write failure prevents the Amazon redirect", async () => {
  writeFails = true;
  const response = await worker.fetch(new Request("https://local.test/go/amazon/17?placement=discord"), env, {});
  writeFails = false;
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("Location"), null);
});

await test("Discord notification generation uses the measured Discord placement", async () => {
  const message = buildDiscordMessage(
    article.content, article.created_at, env.AMAZON_TAG, env.SITE_URL, article.id
  );
  assert.match(message, /\/go\/amazon\/17\?placement=discord/);
  assert.doesNotMatch(message, /https:\/\/www\.amazon\.co\.jp/);
});

console.log(`1..${count}`);
