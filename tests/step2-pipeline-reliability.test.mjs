import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { PipelineD1Mock } from "./helpers/pipeline-d1-mock.mjs";

const source = await fs.readFile(new URL("../src/index.ts", import.meta.url), "utf8");
const exportedSource = `${source}\nexport {
  acquirePipelineRun,
  callGemini,
  handleTestMultiLlm,
  handleExistingPipelineRun,
  normalizeScheduledTime,
  runReliablePipeline,
  runScheduledPipeline,
  validateManualIdempotencyKey
};`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(exportedSource).toString("base64")}`;
const workerModule = await import(moduleUrl);
const {
  acquirePipelineRun,
  callGemini,
  handleTestMultiLlm,
  handleExistingPipelineRun,
  normalizeScheduledTime,
  runReliablePipeline,
  runScheduledPipeline,
  validateManualIdempotencyKey
} = workerModule;
const worker = workerModule.default;

const DUMMY_SECRET = "STEP2_SECRET_MUST_NOT_LEAK";
const DUMMY_TOKEN = "STEP2_BEARER_MUST_NOT_LEAK";
const DUMMY_WEBHOOK = "https://discord.invalid/STEP2_WEBHOOK_MUST_NOT_LEAK";
const FIXED_DATE = new Date("2026-08-10T00:00:00.000Z");

function response(status, data = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function successData(provider) {
  if (provider === "gemini") return { candidates: [{ content: { parts: [{ text: "draft" }] } }] };
  if (provider === "claude") return { content: [{ text: "reviewed" }] };
  return { choices: [{ message: { content: "final article" } }] };
}

function createHarness(options = {}) {
  const db = options.db ?? new PipelineD1Mock(options.dbOptions);
  const calls = [];
  let discordShouldFail = options.discordShouldFail ?? false;
  const runtime = {
    now: () => options.now ?? FIXED_DATE,
    randomUUID: (() => {
      let id = 0;
      return () => `execution-${++id}`;
    })(),
    sleep: async () => {},
    random: () => 0,
    timeouts: { gemini: 10, claude: 10, openai: 10, discord: 10 },
    fetch: async (url) => {
      calls.push(url);
      if (url.includes("googleapis")) return response(200, successData("gemini"));
      if (url.includes("anthropic")) return response(200, successData("claude"));
      if (url.includes("openai")) return response(200, successData("openai"));
      if (url.includes("discord")) {
        return discordShouldFail ? response(500) : new Response(null, { status: 204 });
      }
      throw new Error("unexpected URL");
    }
  };
  const env = {
    DB: db,
    GEMINI_API_KEY: DUMMY_SECRET,
    CLAUDE_API_KEY: DUMMY_SECRET,
    OPENAI_API_KEY: DUMMY_SECRET,
    DISCORD_WEBHOOK_URL: DUMMY_WEBHOOK,
    AMAZON_TAG: "dummy-22",
    OPERATIONS_API_TOKEN: DUMMY_TOKEN
  };
  return {
    db,
    env,
    runtime,
    calls,
    setDiscordFailure(value) { discordShouldFail = value; }
  };
}

function cronSpecification(scheduledTime = 1786320000000) {
  const normalized = normalizeScheduledTime(scheduledTime);
  return {
    triggerType: "cron",
    idempotencyKey: `cron:${normalized.key}`,
    scheduledFor: normalized.iso,
    sourceType: "cron_pro_consensus",
    discordHeader: "cron"
  };
}

function manualSpecification(key = "manual-key") {
  return {
    triggerType: "manual",
    idempotencyKey: `manual:${key}`,
    scheduledFor: null,
    sourceType: "pro_consensus_summary",
    discordHeader: null
  };
}

let testCount = 0;
async function test(name, fn) {
  await fn();
  testCount += 1;
  console.log(`ok ${testCount} - ${name}`);
}

await test("0002 applies after 0001 and preserves a legacy article", async () => {
  const directory = mkdtempSync(join(tmpdir(), "step2-migration-"));
  const database = join(directory, "migration.sqlite");
  try {
    const migrationOne = readFileSync(new URL("../migrations/0001_baseline.sql", import.meta.url), "utf8");
    const migrationTwo = readFileSync(new URL("../migrations/0002_pipeline_reliability.sql", import.meta.url), "utf8");
    const sql = `${migrationOne}\nINSERT INTO curation_logs (source_type,llm_name,content,created_at) VALUES ('legacy','legacy','unchanged','2026-08-10T00:00:00.000Z');\n${migrationTwo}\nINSERT INTO curation_logs (source_type,llm_name,content,created_at) VALUES ('old-worker','legacy','compatible','2026-08-10T00:01:00.000Z');\n`;
    const applied = spawnSync("sqlite3", [database], { input: sql, encoding: "utf8" });
    assert.equal(applied.status, 0, applied.stderr);
    const query = spawnSync("sqlite3", [database,
      "SELECT content || ':' || COALESCE(pipeline_run_id, 'NULL') FROM curation_logs; SELECT COUNT(*) FROM pragma_table_info('pipeline_runs'); SELECT COUNT(*) FROM pragma_index_list('pipeline_runs') WHERE origin = 'u'; SELECT COUNT(*) FROM pragma_foreign_key_list('curation_logs');"
    ], { encoding: "utf8" });
    assert.equal(query.status, 0, query.stderr);
    assert.deepEqual(query.stdout.trim().split("\n"), [
      "unchanged:NULL", "compatible:NULL", "22", "2", "0"
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

await test("SQLite enforces pipeline and article uniqueness", async () => {
  const directory = mkdtempSync(join(tmpdir(), "step2-unique-"));
  const database = join(directory, "unique.sqlite");
  try {
    const migrationOne = readFileSync(new URL("../migrations/0001_baseline.sql", import.meta.url), "utf8");
    const migrationTwo = readFileSync(new URL("../migrations/0002_pipeline_reliability.sql", import.meta.url), "utf8");
    const baseRun = "INSERT INTO pipeline_runs (execution_id,idempotency_key,trigger_type,lease_expires_at,started_at,updated_at) VALUES ('e1','manual:k1','manual','2099-01-01','2026-08-10','2026-08-10');";
    const applied = spawnSync("sqlite3", [database], {
      input: `${migrationOne}\n${migrationTwo}\n${baseRun}\nINSERT INTO curation_logs (source_type,llm_name,content,pipeline_run_id) VALUES ('s','l','one',1);`,
      encoding: "utf8"
    });
    assert.equal(applied.status, 0, applied.stderr);
    for (const duplicate of [
      "INSERT INTO pipeline_runs (execution_id,idempotency_key,trigger_type,lease_expires_at,started_at,updated_at) VALUES ('e1','manual:k2','manual','2099','2026','2026');",
      "INSERT INTO pipeline_runs (execution_id,idempotency_key,trigger_type,lease_expires_at,started_at,updated_at) VALUES ('e2','manual:k1','manual','2099','2026','2026');",
      "INSERT INTO curation_logs (source_type,llm_name,content,pipeline_run_id) VALUES ('s','l','two',1);"
    ]) {
      const result = spawnSync("sqlite3", [database, duplicate], { encoding: "utf8" });
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /UNIQUE constraint failed/);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

await test("0002 contains no destructive or data mutation SQL", async () => {
  const migration = await fs.readFile(new URL("../migrations/0002_pipeline_reliability.sql", import.meta.url), "utf8");
  assert.doesNotMatch(migration, /\b(?:DROP|DELETE|UPDATE)\b/i);
  assert.match(migration, /ALTER TABLE curation_logs ADD COLUMN pipeline_run_id INTEGER/i);
  assert.match(migration, /WHERE pipeline_run_id IS NOT NULL/i);
});

await test("manual idempotency keys enforce length and safe characters", async () => {
  assert.equal(validateManualIdempotencyKey(null), "Idempotency-Key is required");
  assert.equal(validateManualIdempotencyKey(" "), "Invalid Idempotency-Key");
  assert.equal(validateManualIdempotencyKey("bad key"), "Invalid Idempotency-Key");
  assert.equal(validateManualIdempotencyKey("bad\nkey"), "Invalid Idempotency-Key");
  assert.equal(validateManualIdempotencyKey("a".repeat(129)), "Invalid Idempotency-Key");
  assert.equal(validateManualIdempotencyKey("release_2026-08.10:01"), null);
});

await test("scheduledTime uses epoch milliseconds without timezone conversion", async () => {
  const result = normalizeScheduledTime(1786320000123);
  assert.equal(result.key, "1786320000123");
  assert.equal(result.iso, new Date(1786320000123).toISOString());
});

await test("atomic acquisition resolves an ambiguous committed insert", async () => {
  const db = new PipelineD1Mock({ ambiguousRunInsert: true });
  const result = await acquirePipelineRun(db, manualSpecification("ambiguous"), {
    now: () => FIXED_DATE,
    randomUUID: () => "ambiguous-execution"
  });
  assert.equal(result.acquired, true);
  assert.equal(db.state.pipelineRuns.length, 1);
});

await test("same Cron scheduledTime running concurrently executes only once", async () => {
  const harness = createHarness();
  const [first, second] = await Promise.all([
    runScheduledPipeline(harness.env, harness.runtime, 1786320000000),
    runScheduledPipeline(harness.env, harness.runtime, 1786320000000)
  ]);
  assert.equal(harness.db.state.pipelineRuns.length, 1);
  assert.equal(harness.db.state.articles.length, 1);
  assert.equal(harness.calls.filter((url) => url.includes("googleapis")).length, 1);
  assert.equal(harness.calls.filter((url) => url.includes("discord")).length, 1);
  assert.deepEqual(new Set([first.outcome, second.outcome]), new Set(["completed", "in_progress"]));
});

await test("Cron scheduledTime values on different UTC days create separate runs", async () => {
  const harness = createHarness();
  await runScheduledPipeline(harness.env, harness.runtime, 1786320000000);
  const nextDay = 1786320000000 + (24 * 60 * 60 * 1000);
  const nextDayHarness = createHarness({ db: harness.db, now: new Date(FIXED_DATE.getTime() + (24 * 60 * 60 * 1000)) });
  nextDayHarness.runtime.randomUUID = () => "next-day-execution";
  await runScheduledPipeline(nextDayHarness.env, nextDayHarness.runtime, nextDay);
  assert.equal(harness.db.state.pipelineRuns.length, 2);
  assert.equal(harness.db.state.articles.length, 2);
  assert.equal(harness.calls.filter((url) => url.includes("googleapis")).length, 1);
  assert.equal(nextDayHarness.calls.filter((url) => url.includes("googleapis")).length, 1);
});

await test("same manual key does not run LLM twice", async () => {
  const harness = createHarness();
  const first = await runReliablePipeline(harness.env, manualSpecification("same"), harness.runtime);
  const callsAfterFirst = harness.calls.length;
  const second = await runReliablePipeline(harness.env, manualSpecification("same"), harness.runtime);
  assert.equal(first.outcome, "completed");
  assert.equal(second.outcome, "completed");
  assert.equal(harness.calls.length, callsAfterFirst);
  assert.equal(harness.db.state.articles.length, 1);
});

await test("Cron and manual namespaces do not collide", async () => {
  const harness = createHarness();
  await runReliablePipeline(harness.env, cronSpecification(123), harness.runtime);
  await runReliablePipeline(harness.env, manualSpecification("123"), harness.runtime);
  assert.deepEqual(harness.db.state.pipelineRuns.map((run) => run.idempotency_key), ["cron:123", "manual:123"]);
});

await test("manual endpoint rejects missing and invalid Idempotency-Key", async () => {
  for (const key of [null, "bad key"]) {
    const headers = { Authorization: `Bearer ${DUMMY_TOKEN}` };
    if (key !== null) headers["Idempotency-Key"] = key;
    const result = await worker.fetch(new Request("https://local.test/test-multillm", {
      method: "POST",
      headers
    }), { OPERATIONS_API_TOKEN: DUMMY_TOKEN }, {});
    assert.equal(result.status, 400);
    const body = await result.text();
    if (key !== null) assert.equal(body.includes(key), false);
  }
});

for (const failedProvider of ["gemini", "claude", "openai"]) {
  await test(`${failedProvider} failure records a failed run without article`, async () => {
    const harness = createHarness();
    const baseFetch = harness.runtime.fetch;
    harness.runtime.fetch = async (url, init) => {
      if (url.includes(failedProvider === "gemini" ? "googleapis" : failedProvider === "claude" ? "anthropic" : "openai")) {
        return response(400);
      }
      return baseFetch(url, init);
    };
    await assert.rejects(runReliablePipeline(harness.env, manualSpecification(failedProvider), harness.runtime));
    assert.equal(harness.db.state.pipelineRuns[0].status, "failed");
    assert.equal(harness.db.state.pipelineRuns[0].stage, failedProvider);
    assert.equal(harness.db.state.articles.length, 0);
  });
}

await test("D1 save failure records failed and never sends Discord", async () => {
  const harness = createHarness({ dbOptions: { failArticleInsert: true } });
  await assert.rejects(runReliablePipeline(harness.env, manualSpecification("d1-fail"), harness.runtime));
  assert.equal(harness.db.state.pipelineRuns[0].status, "failed");
  assert.equal(harness.db.state.pipelineRuns[0].stage, "d1_save");
  assert.equal(harness.calls.some((url) => url.includes("discord")), false);
});

await test("Discord failure preserves article and notification failure state", async () => {
  const harness = createHarness({ discordShouldFail: true });
  await assert.rejects(runReliablePipeline(harness.env, manualSpecification("discord-fail"), harness.runtime));
  const run = harness.db.state.pipelineRuns[0];
  assert.equal(run.status, "saved");
  assert.equal(run.stage, "discord");
  assert.equal(run.notification_status, "failed");
  assert.equal(run.notification_attempt_count, 1);
  assert.equal(harness.db.state.articles.length, 1);
});

await test("Discord retry uses saved article without rerunning LLM", async () => {
  const harness = createHarness({ discordShouldFail: true });
  await assert.rejects(runReliablePipeline(harness.env, manualSpecification("discord-retry"), harness.runtime));
  const llmCalls = harness.calls.filter((url) => !url.includes("discord")).length;
  harness.setDiscordFailure(false);
  const result = await runReliablePipeline(harness.env, manualSpecification("discord-retry"), harness.runtime);
  assert.equal(result.outcome, "completed");
  assert.equal(harness.calls.filter((url) => !url.includes("discord")).length, llmCalls);
  assert.equal(harness.db.state.pipelineRuns[0].notification_attempt_count, 2);
  assert.equal(harness.db.state.pipelineRuns[0].notification_status, "sent");
});

await test("completed run suppresses all repeated work", async () => {
  const harness = createHarness();
  await runReliablePipeline(harness.env, manualSpecification("complete"), harness.runtime);
  const calls = harness.calls.length;
  await runReliablePipeline(harness.env, manualSpecification("complete"), harness.runtime);
  assert.equal(harness.calls.length, calls);
});

await test("failed run is not automatically restarted", async () => {
  const harness = createHarness();
  harness.db.seedRun({ idempotency_key: "manual:failed", status: "failed", stage: "claude" });
  const result = await runReliablePipeline(harness.env, manualSpecification("failed"), harness.runtime);
  assert.equal(result.outcome, "failed");
  assert.equal(harness.calls.length, 0);
});

await test("active running run returns in_progress without external calls", async () => {
  const harness = createHarness();
  harness.db.seedRun({ idempotency_key: "manual:active", lease_expires_at: "2099-01-01T00:00:00.000Z" });
  const result = await runReliablePipeline(harness.env, manualSpecification("active"), harness.runtime);
  assert.equal(result.outcome, "in_progress");
  assert.equal(harness.calls.length, 0);
});

await test("stale running without article requires reconciliation without mutation", async () => {
  const harness = createHarness();
  const run = harness.db.seedRun({
    idempotency_key: "manual:stale-empty",
    lease_expires_at: "2026-08-09T00:00:00.000Z"
  });
  const result = await runReliablePipeline(harness.env, manualSpecification("stale-empty"), harness.runtime);
  assert.equal(result.outcome, "reconciliation_required");
  assert.equal(run.status, "running");
  assert.equal(run.error_code, null);
  assert.equal(harness.calls.length, 0);
});

await test("running run with saved article requires state repair without sending", async () => {
  const harness = createHarness();
  const run = harness.db.seedRun({
    idempotency_key: "manual:stale-saved",
    lease_expires_at: "2026-08-09T00:00:00.000Z"
  });
  harness.db.seedArticle({ pipeline_run_id: run.id, content: "already saved" });
  const result = await runReliablePipeline(harness.env, manualSpecification("stale-saved"), harness.runtime);
  assert.equal(result.outcome, "reconciliation_required");
  assert.equal(run.status, "running");
  assert.equal(harness.calls.length, 0);
});

await test("ambiguous committed D1 batch is reconciled without duplicate article", async () => {
  const harness = createHarness({ dbOptions: { ambiguousBatchCommit: true } });
  const result = await runReliablePipeline(harness.env, manualSpecification("ambiguous-batch"), harness.runtime);
  assert.equal(result.outcome, "completed");
  assert.equal(harness.db.state.articles.length, 1);
  assert.equal(harness.db.state.pipelineRuns[0].article_id, harness.db.state.articles[0].id);
});

await test("same pipeline_run_id rejects a second article", async () => {
  const db = new PipelineD1Mock();
  db.seedArticle({ pipeline_run_id: 1 });
  assert.throws(() => db.seedArticle({ pipeline_run_id: 1 }), /UNIQUE/);
});

await test("pipeline save uses D1 batch", async () => {
  const harness = createHarness();
  await runReliablePipeline(harness.env, manualSpecification("batch"), harness.runtime);
  assert.equal(harness.db.state.batchCalls, 1);
});

await test("notification sending state prevents concurrent duplicate sends", async () => {
  const harness = createHarness();
  const run = harness.db.seedRun({
    idempotency_key: "manual:sending",
    status: "saved",
    stage: "discord",
    notification_status: "sending"
  });
  harness.db.seedArticle({ pipeline_run_id: run.id });
  const result = await handleExistingPipelineRun(harness.env, run, manualSpecification("sending"), harness.runtime);
  assert.equal(result.outcome, "notification_in_progress");
  assert.equal(harness.calls.length, 0);
});

await test("sanitized pipeline state and logs do not leak secrets", async () => {
  const harness = createHarness();
  harness.runtime.fetch = async () => response(401, {
    secret: DUMMY_SECRET,
    token: DUMMY_TOKEN,
    webhook: DUMMY_WEBHOOK
  });
  const captured = [];
  const originalError = console.error;
  console.error = (...args) => captured.push(JSON.stringify(args));
  try {
    await assert.rejects(runScheduledPipeline(harness.env, harness.runtime, 1786320000999));
  } finally {
    console.error = originalError;
  }
  const serializedState = JSON.stringify(harness.db.state);
  const combined = `${serializedState}\n${captured.join("\n")}`;
  assert.equal(combined.includes(DUMMY_SECRET), false);
  assert.equal(combined.includes(DUMMY_TOKEN), false);
  assert.equal(combined.includes(DUMMY_WEBHOOK), false);
});

await test("operations authentication and method checks still run before idempotency validation", async () => {
  const getResult = await worker.fetch(new Request("https://local.test/test-multillm"), {}, {});
  assert.equal(getResult.status, 405);
  assert.equal(getResult.headers.get("Allow"), "POST");
  const unauthorized = await worker.fetch(new Request("https://local.test/test-multillm", {
    method: "POST",
    headers: { "Idempotency-Key": "valid" }
  }), { OPERATIONS_API_TOKEN: DUMMY_TOKEN }, {});
  assert.equal(unauthorized.status, 401);
});

await test("pipeline completes normally inside the eight minute deadline", async () => {
  const harness = createHarness();
  const result = await runReliablePipeline(harness.env, manualSpecification("deadline-normal"), harness.runtime);
  assert.equal(result.outcome, "completed");
  assert.equal(harness.db.state.pipelineRuns[0].status, "completed");
});

await test("global deadline aborts Gemini and leaves no article or Discord call", async () => {
  const harness = createHarness();
  let current = new Date(FIXED_DATE);
  harness.runtime.now = () => current;
  harness.runtime.fetch = async (url, init) => {
    harness.calls.push(url);
    current = new Date(FIXED_DATE.getTime() + (8 * 60 * 1000) - 2);
    return new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        current = new Date(FIXED_DATE.getTime() + (8 * 60 * 1000));
        reject(new Error("aborted"));
      }, { once: true });
    });
  };
  await assert.rejects(
    runReliablePipeline(harness.env, manualSpecification("deadline-gemini"), harness.runtime),
    (error) => error.errorCode === "pipeline_deadline_exceeded"
  );
  assert.equal(harness.db.state.pipelineRuns[0].status, "failed");
  assert.equal(harness.db.state.pipelineRuns[0].error_code, "pipeline_deadline_exceeded");
  assert.equal(harness.db.state.articles.length, 0);
  assert.equal(harness.calls.some((url) => url.includes("discord")), false);
});

await test("global remaining time shorter than stage timeout aborts the active fetch", async () => {
  let aborted = false;
  const start = new Date();
  await assert.rejects(callGemini(DUMMY_SECRET, {
    now: () => new Date(),
    deadlineAt: start.getTime() + 5,
    timeouts: { gemini: 45_000 },
    fetch: async (url, init) => new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        aborted = true;
        reject(new Error("aborted"));
      }, { once: true });
    })
  }), (error) => error.errorCode === "pipeline_deadline_exceeded");
  assert.equal(aborted, true);
});

await test("retry wait that would cross the global deadline is not started", async () => {
  let calls = 0;
  let sleeps = 0;
  const now = new Date("2026-08-10T00:00:00.000Z");
  await assert.rejects(callGemini(DUMMY_SECRET, {
    now: () => now,
    deadlineAt: now.getTime() + 100,
    random: () => 0,
    sleep: async () => { sleeps += 1; },
    fetch: async () => {
      calls += 1;
      return response(500);
    }
  }), (error) => error.errorCode === "pipeline_deadline_exceeded");
  assert.equal(calls, 1);
  assert.equal(sleeps, 0);
});

await test("deadline after article save preserves pending article and skips Discord", async () => {
  let current = new Date(FIXED_DATE);
  const db = new PipelineD1Mock({
    afterBatch: async () => { current = new Date(FIXED_DATE.getTime() + (8 * 60 * 1000)); }
  });
  const harness = createHarness({ db });
  harness.runtime.now = () => current;
  await assert.rejects(
    runReliablePipeline(harness.env, manualSpecification("deadline-after-save"), harness.runtime),
    (error) => error.errorCode === "pipeline_deadline_exceeded"
  );
  assert.equal(db.state.articles.length, 1);
  assert.equal(db.state.pipelineRuns[0].status, "saved");
  assert.equal(db.state.pipelineRuns[0].notification_status, "pending");
  assert.equal(harness.calls.some((url) => url.includes("discord")), false);
});

await test("manual active, rolling hour, and UTC daily limits reject without side effects", async () => {
  for (const seed of [
    { status: "running", started_at: "2026-08-09T22:00:00.000Z" },
    { status: "completed", started_at: "2026-08-09T23:30:00.000Z" },
    [
      { status: "completed", started_at: "2026-08-09T01:00:00.000Z" },
      { status: "failed", started_at: "2026-08-09T02:00:00.000Z" }
    ]
  ]) {
    const db = new PipelineD1Mock();
    for (const values of Array.isArray(seed) ? seed : [seed]) db.seedRun({ ...values, trigger_type: "manual" });
    const harness = createHarness({ db, now: new Date("2026-08-09T23:45:00.000Z") });
    const before = db.state.pipelineRuns.length;
    const responseResult = await handleTestMultiLlm(new Request("https://local.test/test-multillm", {
      method: "POST", headers: { "Idempotency-Key": `limit-${before}` }
    }), harness.env, harness.runtime);
    assert.equal(responseResult.status, 429);
    assert.ok(Number(responseResult.headers.get("Retry-After")) > 0);
    assert.equal(responseResult.headers.get("Cache-Control"), "no-store");
    assert.equal(db.state.pipelineRuns.length, before);
    assert.equal(harness.calls.length, 0);
    assert.equal(db.state.articles.length, 0);
  }
});

await test("same Cron key remains idempotent while a second same-day Cron key is rejected", async () => {
  const harness = createHarness();
  const first = await runScheduledPipeline(harness.env, harness.runtime, 1786320000000);
  const repeated = await runScheduledPipeline(harness.env, harness.runtime, 1786320000000);
  assert.equal(repeated.outcome, first.outcome);
  await assert.rejects(
    runScheduledPipeline(harness.env, harness.runtime, 1786320060000),
    (error) => error.errorCode === "pipeline_limit_exceeded"
  );
  assert.equal(harness.db.state.pipelineRuns.length, 1);
  assert.equal(harness.db.state.articles.length, 1);
});

await test("global daily limit rejects a fourth run and keeps manual and Cron trigger budgets separate", async () => {
  const db = new PipelineD1Mock();
  db.seedRun({ trigger_type: "manual", status: "completed", started_at: "2026-08-10T00:01:00.000Z" });
  db.seedRun({ trigger_type: "manual", status: "failed", started_at: "2026-08-10T02:01:00.000Z" });
  const cron = await acquirePipelineRun(db, cronSpecification(1786320000000), {
    now: () => new Date("2026-08-10T04:00:00.000Z"), randomUUID: () => "global-third"
  });
  assert.equal(cron.acquired, true);
  await assert.rejects(acquirePipelineRun(db, manualSpecification("global-fourth"), {
    now: () => new Date("2026-08-10T05:30:00.000Z"), randomUUID: () => "global-fourth"
  }), (error) => error.errorCode === "pipeline_limit_exceeded");
  assert.equal(db.state.pipelineRuns.length, 3);
});

await test("different manual keys racing cannot exceed the atomic active limit", async () => {
  const db = new PipelineD1Mock();
  const runtime = { now: () => FIXED_DATE };
  const results = await Promise.allSettled([
    acquirePipelineRun(db, manualSpecification("race-a"), { ...runtime, randomUUID: () => "race-a" }),
    acquirePipelineRun(db, manualSpecification("race-b"), { ...runtime, randomUUID: () => "race-b" })
  ]);
  assert.equal(results.filter((result) => result.status === "fulfilled").length, 1);
  assert.equal(results.filter((result) => result.status === "rejected" && result.reason.errorCode === "pipeline_limit_exceeded").length, 1);
  assert.equal(db.state.pipelineRuns.length, 1);
  assert.match(source, /INSERT INTO pipeline_runs[\s\S]*SELECT[\s\S]*WHERE/);
});

await test("budget query and conditional insert failures fail closed", async () => {
  for (const dbOptions of [{ failConditionalInsert: true }, { failBudgetQuery: true }]) {
    const db = new PipelineD1Mock(dbOptions);
    if (dbOptions.failBudgetQuery) db.seedRun({ trigger_type: "manual", status: "running" });
    const harness = createHarness({ db });
    const result = await handleTestMultiLlm(new Request("https://local.test/test-multillm", {
      method: "POST", headers: { "Idempotency-Key": "fail-closed" }
    }), harness.env, harness.runtime);
    assert.equal(result.status, 503);
    assert.equal(harness.calls.length, 0);
    assert.equal(db.state.articles.length, 0);
  }
});

await test("Discord ambiguous network result keeps saved article in sending without retry", async () => {
  const harness = createHarness();
  harness.runtime.fetch = async (url) => {
    harness.calls.push(url);
    if (url.includes("googleapis")) return response(200, successData("gemini"));
    if (url.includes("anthropic")) return response(200, successData("claude"));
    if (url.includes("openai")) return response(200, successData("openai"));
    throw new Error("ambiguous network failure");
  };
  await assert.rejects(runReliablePipeline(harness.env, manualSpecification("discord-ambiguous"), harness.runtime));
  const run = harness.db.state.pipelineRuns[0];
  assert.equal(run.status, "saved");
  assert.equal(run.stage, "discord");
  assert.equal(run.notification_status, "sending");
  assert.equal(harness.db.state.articles.length, 1);
  assert.equal(harness.calls.filter((url) => url.includes("discord")).length, 1);
});

await test("existing stage timeouts and retry limits remain present", async () => {
  assert.match(source, /gemini:\s*45_000/);
  assert.match(source, /claude:\s*60_000/);
  assert.match(source, /openai:\s*60_000/);
  assert.match(source, /discord:\s*10_000/);
  assert.match(source, /const LLM_MAX_ATTEMPTS = 2/);
  assert.match(source, /const DISCORD_MAX_ATTEMPTS = 3/);
});

console.log(`1..${testCount}`);
