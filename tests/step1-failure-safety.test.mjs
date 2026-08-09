import assert from "node:assert/strict";
import fs from "node:fs/promises";

const sourcePath = new URL("../src/index.ts", import.meta.url);
const source = await fs.readFile(sourcePath, "utf8");
const exportedSource = `${source}\nexport {
  OperationError,
  callGemini,
  callClaude,
  callOpenAI,
  parseRetryAfter,
  requestWithRetry,
  runScheduledPipeline,
  saveToD1,
  sendAutomatedReport,
  sendToDiscord
};`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(exportedSource).toString("base64")}`;
const workerModule = await import(moduleUrl);

const {
  callGemini,
  callClaude,
  callOpenAI,
  parseRetryAfter,
  runScheduledPipeline,
  saveToD1,
  sendToDiscord
} = workerModule;
const worker = workerModule.default;

const DUMMY_SECRET = "DUMMY_SECRET_MUST_NOT_LEAK_123";
const DUMMY_TOKEN = "DUMMY_BEARER_MUST_NOT_LEAK_456";
const DUMMY_WEBHOOK = "https://discord.invalid/api/webhooks/DUMMY_URL_MUST_NOT_LEAK";

function response(status, data = {}, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...headers }
  });
}

function successData(provider, text = `${provider} text`) {
  if (provider === "gemini") {
    return { candidates: [{ content: { parts: [{ text }] } }] };
  }
  if (provider === "claude") return { content: [{ text }] };
  return { choices: [{ message: { content: text } }] };
}

const providerCalls = {
  gemini: (runtime) => callGemini(DUMMY_SECRET, runtime),
  claude: (runtime) => callClaude(DUMMY_SECRET, "draft", runtime),
  openai: (runtime) => callOpenAI(DUMMY_SECRET, "reviewed", runtime)
};

function runtimeWith(fetch, timeout = 5) {
  return {
    fetch,
    sleep: async () => {},
    random: () => 0,
    timeouts: { gemini: timeout, claude: timeout, openai: timeout, discord: timeout }
  };
}

async function expectOperationError(promise, expected) {
  await assert.rejects(promise, (error) => {
    assert.equal(error.message, "Operation failed");
    for (const [key, value] of Object.entries(expected)) assert.equal(error[key], value);
    return true;
  });
}

let testCount = 0;
async function test(name, fn) {
  await fn();
  testCount += 1;
  console.log(`ok ${testCount} - ${name}`);
}

await test("Retry-After seconds, HTTP-date, invalid and cap", async () => {
  assert.equal(parseRetryAfter("5", 0), 5000);
  assert.equal(parseRetryAfter("999", 0), 30000);
  assert.equal(parseRetryAfter("-1", 0), null);
  assert.equal(parseRetryAfter("invalid", 0), null);
  assert.equal(parseRetryAfter(new Date(10_000).toUTCString(), 0), 10_000);
});

for (const provider of ["gemini", "claude", "openai"]) {
  await test(`${provider} 200 validates non-empty text`, async () => {
    let calls = 0;
    const result = await providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      return response(200, successData(provider));
    }));
    assert.equal(result, `${provider} text`);
    assert.equal(calls, 1);
  });

  await test(`${provider} retryable failure retries once then succeeds`, async () => {
    let calls = 0;
    const result = await providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      if (calls === 1) {
        if (provider === "gemini") return response(429, {}, { "Retry-After": "5" });
        if (provider === "claude") return response(500);
        throw new Error("network");
      }
      return response(200, successData(provider));
    }));
    assert.equal(result, `${provider} text`);
    assert.equal(calls, 2);
  });

  await test(`${provider} client error is not retried`, async () => {
    let calls = 0;
    await expectOperationError(providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      return response(provider === "claude" ? 401 : 400);
    })), { provider, errorCode: "http_error", retryable: false, attempt: 1 });
    assert.equal(calls, 1);
  });

  await test(`${provider} malformed JSON is not retried`, async () => {
    let calls = 0;
    await expectOperationError(providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      return new Response("{", { status: 200 });
    })), { provider, errorCode: "invalid_json", retryable: false });
    assert.equal(calls, 1);
  });

  await test(`${provider} missing or blank text is rejected without retry`, async () => {
    let calls = 0;
    await expectOperationError(providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      return response(200, successData(provider, "   "));
    })), { provider, errorCode: "invalid_response", retryable: false });
    assert.equal(calls, 1);
  });

  await test(`${provider} timeout retries once then succeeds`, async () => {
    let calls = 0;
    const result = await providerCalls[provider](runtimeWith((url, init) => {
      calls += 1;
      if (calls === 2) return Promise.resolve(response(200, successData(provider)));
      return Promise.resolve({
        ok: true,
        async json() {
          return new Promise((resolve, reject) => {
            init.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
          });
        }
      });
    }, 1));
    assert.equal(result, `${provider} text`);
    assert.equal(calls, 2);
  });

  await test(`${provider} retry limit is two attempts`, async () => {
    let calls = 0;
    await expectOperationError(providerCalls[provider](runtimeWith(async () => {
      calls += 1;
      return response(500);
    })), { provider, errorCode: "http_error", retryable: true, attempt: 2 });
    assert.equal(calls, 2);
  });
}

await test("Discord 204 succeeds", async () => {
  let calls = 0;
  await sendToDiscord(DUMMY_WEBHOOK, "content", runtimeWith(async () => {
    calls += 1;
    return new Response(null, { status: 204 });
  }));
  assert.equal(calls, 1);
});

for (const scenario of ["429", "500", "network", "timeout"]) {
  await test(`Discord ${scenario} retries then succeeds`, async () => {
    let calls = 0;
    const runtime = runtimeWith((url, init) => {
      calls += 1;
      if (calls === 2) return Promise.resolve(new Response(null, { status: 204 }));
      if (scenario === "429") return Promise.resolve(response(429, {}, { "Retry-After": "1" }));
      if (scenario === "500") return Promise.resolve(response(500));
      if (scenario === "network") return Promise.reject(new Error("network"));
      return new Promise((resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    }, 1);
    await sendToDiscord(DUMMY_WEBHOOK, "content", runtime);
    assert.equal(calls, 2);
  });
}

await test("Discord 400 is not retried", async () => {
  let calls = 0;
  await expectOperationError(sendToDiscord(DUMMY_WEBHOOK, "content", runtimeWith(async () => {
    calls += 1;
    return response(400);
  })), { provider: "discord", retryable: false, attempt: 1 });
  assert.equal(calls, 1);
});

await test("Discord retry limit is three attempts", async () => {
  let calls = 0;
  await expectOperationError(sendToDiscord(DUMMY_WEBHOOK, "content", runtimeWith(async () => {
    calls += 1;
    return response(500);
  })), { provider: "discord", retryable: true, attempt: 3 });
  assert.equal(calls, 3);
});

function dbMock({ fail = false } = {}) {
  const state = { writes: 0 };
  return {
    state,
    prepare() {
      return {
        bind() {
          return {
            async run() {
              state.writes += 1;
              if (fail) throw new Error("DUMMY_DB_INTERNAL_DETAIL");
              return { success: true };
            }
          };
        }
      };
    }
  };
}

await test("D1 insert succeeds", async () => {
  const db = dbMock();
  await saveToD1(db, "source", "llm", "content", new Date().toISOString());
  assert.equal(db.state.writes, 1);
});

await test("Missing D1 binding rejects", async () => {
  await expectOperationError(saveToD1(null, "source", "llm", "content", "time"), {
    provider: "d1",
    errorCode: "binding_missing"
  });
});

await test("D1 insert throw is sanitized", async () => {
  await expectOperationError(saveToD1(dbMock({ fail: true }), "source", "llm", "content", "time"), {
    provider: "d1",
    errorCode: "write_failed"
  });
});

function pipelineRuntime(overrides = {}) {
  const calls = [];
  const runtime = runtimeWith(async (url) => {
    calls.push(url);
    if (url.includes("googleapis")) return response(200, successData("gemini"));
    if (url.includes("anthropic")) return response(200, successData("claude"));
    if (url.includes("openai")) return response(200, successData("openai"));
    if (url.includes("discord")) return new Response(null, { status: 204 });
    throw new Error("unexpected URL");
  });
  Object.assign(runtime, overrides);
  return { runtime, calls };
}

function pipelineEnv(db = dbMock()) {
  return {
    GEMINI_API_KEY: DUMMY_SECRET,
    CLAUDE_API_KEY: DUMMY_SECRET,
    OPENAI_API_KEY: DUMMY_SECRET,
    DISCORD_WEBHOOK_URL: DUMMY_WEBHOOK,
    AMAZON_TAG: "dummy-22",
    DB: db
  };
}

await test("Cron success saves before Discord", async () => {
  const { runtime, calls } = pipelineRuntime();
  const db = dbMock();
  await runScheduledPipeline(pipelineEnv(db), runtime);
  assert.equal(db.state.writes, 1);
  assert.equal(calls.filter((url) => url.includes("discord")).length, 1);
});

for (const failedProvider of ["gemini", "claude", "openai", "discord"]) {
  await test(`Cron rejects on ${failedProvider} failure`, async () => {
    const calls = [];
    const failureHost = {
      gemini: "googleapis",
      claude: "anthropic",
      openai: "openai",
      discord: "discord"
    }[failedProvider];
    const runtime = runtimeWith(async (url) => {
      calls.push(url);
      if (url.includes(failureHost)) return response(400);
      if (url.includes("googleapis")) return response(200, successData("gemini"));
      if (url.includes("anthropic")) return response(200, successData("claude"));
      if (url.includes("openai")) return response(200, successData("openai"));
      return new Response(null, { status: 204 });
    });
    await assert.rejects(runScheduledPipeline(pipelineEnv(), runtime));
  });
}

await test("Cron D1 failure rejects and never calls Discord", async () => {
  const { runtime, calls } = pipelineRuntime();
  await assert.rejects(runScheduledPipeline(pipelineEnv(dbMock({ fail: true })), runtime));
  assert.equal(calls.filter((url) => url.includes("discord")).length, 0);
});

await test("/test returns 500 on Discord failure with generic body", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => response(400, { detail: DUMMY_SECRET });
  try {
    const request = new Request("https://local.test/test", {
      method: "POST",
      headers: { Authorization: `Bearer ${DUMMY_TOKEN}` }
    });
    const result = await worker.fetch(request, {
      OPERATIONS_API_TOKEN: DUMMY_TOKEN,
      DISCORD_WEBHOOK_URL: DUMMY_WEBHOOK,
      AMAZON_TAG: "dummy-22"
    }, {});
    assert.equal(result.status, 500);
    assert.equal(await result.text(), "Operation failed");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

await test("/test-multillm returns 500 when D1 insert fails", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (url.includes("googleapis")) return response(200, successData("gemini"));
    if (url.includes("anthropic")) return response(200, successData("claude"));
    return response(200, successData("openai"));
  };
  try {
    const request = new Request("https://local.test/test-multillm", {
      method: "POST",
      headers: { Authorization: `Bearer ${DUMMY_TOKEN}` }
    });
    const result = await worker.fetch(request, {
      OPERATIONS_API_TOKEN: DUMMY_TOKEN,
      GEMINI_API_KEY: DUMMY_SECRET,
      CLAUDE_API_KEY: DUMMY_SECRET,
      OPENAI_API_KEY: DUMMY_SECRET,
      DB: dbMock({ fail: true })
    }, {});
    assert.equal(result.status, 500);
    assert.deepEqual(await result.json(), { status: "error", message: "Operation failed" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

await test("operation responses and structured logs do not leak dummy secrets", async () => {
  const captured = [];
  const originalError = console.error;
  console.error = (...args) => captured.push(JSON.stringify(args));
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => response(401, { secret: DUMMY_SECRET, webhook: DUMMY_WEBHOOK });
  try {
    const request = new Request("https://local.test/test", {
      method: "POST",
      headers: { Authorization: `Bearer ${DUMMY_TOKEN}` }
    });
    const result = await worker.fetch(request, {
      OPERATIONS_API_TOKEN: DUMMY_TOKEN,
      DISCORD_WEBHOOK_URL: DUMMY_WEBHOOK
    }, {});
    const combined = `${await result.text()}\n${captured.join("\n")}`;
    assert.equal(combined.includes(DUMMY_SECRET), false);
    assert.equal(combined.includes(DUMMY_TOKEN), false);
    assert.equal(combined.includes(DUMMY_WEBHOOK), false);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});

await test("authentication method and 401 contracts remain unchanged", async () => {
  const getResult = await worker.fetch(new Request("https://local.test/test", { method: "GET" }), {}, {});
  assert.equal(getResult.status, 405);
  assert.equal(getResult.headers.get("Allow"), "POST");
  assert.equal(getResult.headers.get("Cache-Control"), "no-store");

  const unauthorized = await worker.fetch(new Request("https://local.test/view-logs"), {
    OPERATIONS_API_TOKEN: DUMMY_TOKEN
  }, {});
  assert.equal(unauthorized.status, 401);
  assert.equal(unauthorized.headers.get("WWW-Authenticate"), "Bearer");
  assert.equal(unauthorized.headers.get("Cache-Control"), "no-store");
});

await test("all operations endpoint method and authentication contracts remain unchanged", async () => {
  const contracts = [
    ["/test-multillm", "POST"],
    ["/view-logs", "GET"],
    ["/test-discord", "POST"],
    ["/test", "POST"]
  ];

  for (const [path, allowedMethod] of contracts) {
    const wrongMethod = allowedMethod === "GET" ? "POST" : "GET";
    const methodResult = await worker.fetch(
      new Request(`https://local.test${path}`, { method: wrongMethod }),
      {},
      {}
    );
    assert.equal(methodResult.status, 405);
    assert.equal(methodResult.headers.get("Allow"), allowedMethod);
    assert.equal(methodResult.headers.get("Cache-Control"), "no-store");

    const unauthorized = await worker.fetch(
      new Request(`https://local.test${path}`, { method: allowedMethod }),
      { OPERATIONS_API_TOKEN: DUMMY_TOKEN },
      {}
    );
    assert.equal(unauthorized.status, 401);
    assert.equal(unauthorized.headers.get("WWW-Authenticate"), "Bearer");
    assert.equal(unauthorized.headers.get("Cache-Control"), "no-store");
  }

  const getTask = await worker.fetch(new Request("https://local.test/get-task"), {}, {});
  assert.equal(getTask.status, 404);
});

function publicPageDb() {
  const rows = [{
    id: 25,
    source_type: "cron_pro_consensus",
    llm_name: "Pro-Consensus Pipeline",
    content: "# テスト記事\n生成AIとクラウドの最新動向",
    created_at: "2026-08-09T23:00:00.000Z"
  }];

  return {
    prepare(sql) {
      return {
        bind() {
          return this;
        },
        async first() {
          if (sql.includes("COUNT(*)")) return { total: 9 };
          if (sql.includes("WHERE id = ?")) return rows[0];
          return null;
        },
        async all() {
          return { results: rows };
        }
      };
    }
  };
}

await test("public SEO pages retain canonical, links, JSON-LD, sitemap and robots", async () => {
  const env = {
    DB: publicPageDb(),
    SITE_URL: "https://cloudflare-webhook.tyansaku3325.workers.dev",
    AMAZON_TAG: "dummy-22"
  };

  const home = await worker.fetch(new Request("https://different-host.invalid/"), env, {});
  const homeHtml = await home.text();
  assert.equal(home.status, 200);
  assert.match(homeHtml, /google-site-verification/);
  assert.match(homeHtml, /rel="canonical" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/"/);
  assert.match(homeHtml, /rel="next" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/\?page=2"/);
  assert.match(homeHtml, /property="og:url" content="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/"/);
  assert.match(homeHtml, /href="\/article\/25">続きを読む/);
  assert.match(homeHtml, /amazon\.co\.jp/);

  const pageTwo = await worker.fetch(new Request("https://different-host.invalid/?page=2"), env, {});
  const pageTwoHtml = await pageTwo.text();
  assert.equal(pageTwo.status, 200);
  assert.match(pageTwoHtml, /canonical" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/\?page=2"/);
  assert.match(pageTwoHtml, /rel="prev" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/"/);
  assert.match(pageTwoHtml, /2ページ目/);

  const outOfRange = await worker.fetch(new Request("https://local.test/?page=3"), env, {});
  assert.equal(outOfRange.status, 404);

  const article = await worker.fetch(new Request("https://different-host.invalid/article/25"), env, {});
  const articleHtml = await article.text();
  assert.equal(article.status, 200);
  assert.match(articleHtml, /canonical" href="https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/article\/25"/);
  assert.match(articleHtml, /mainEntityOfPage/);
  assert.match(articleHtml, /https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/article\/25/);

  const sitemap = await worker.fetch(new Request("https://different-host.invalid/sitemap.xml"), env, {});
  const sitemapXml = await sitemap.text();
  assert.equal(sitemap.status, 200);
  assert.match(sitemap.headers.get("Content-Type"), /application\/xml/);
  assert.match(sitemapXml, /<loc>https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/article\/25<\/loc>/);

  const robots = await worker.fetch(new Request("https://different-host.invalid/robots.txt"), env, {});
  const robotsText = await robots.text();
  assert.equal(robots.status, 200);
  assert.match(robots.headers.get("Content-Type"), /text\/plain/);
  assert.match(robotsText, /Sitemap: https:\/\/cloudflare-webhook\.tyansaku3325\.workers\.dev\/sitemap\.xml/);
});

console.log(`1..${testCount}`);
