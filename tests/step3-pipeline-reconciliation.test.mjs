import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";

const source = await fs.readFile(new URL("../src/index.ts", import.meta.url), "utf8");
const exportedSource = `${source}\nexport { classifyReconciliationRun, handlePipelineReconciliationAction, handlePipelineReconciliationList };`;
const workerModule = await import(`data:text/javascript;base64,${Buffer.from(exportedSource).toString("base64")}`);
const { classifyReconciliationRun, handlePipelineReconciliationAction, handlePipelineReconciliationList } = workerModule;
const worker = workerModule.default;
const migrations = await Promise.all([1, 2, 3].map((number) => fs.readFile(
  new URL(`../migrations/000${number}_${["baseline", "pipeline_reliability", "pipeline_reconciliation_audit"][number - 1]}.sql`, import.meta.url), "utf8"
)));

class D1Sqlite {
  constructor() {
    this.sqlite = new DatabaseSync(":memory:");
    this.sqlite.exec(migrations.join("\n"));
  }
  prepare(sql) {
    const statement = this.sqlite.prepare(sql);
    let args = [];
    return {
      bind(...values) { args = values; return this; },
      async first() { return statement.get(...args) ?? null; },
      async all() { return { results: statement.all(...args) }; },
      async run() { return { meta: { changes: statement.run(...args).changes } }; }
    };
  }
  async batch(statements) {
    this.sqlite.exec("BEGIN IMMEDIATE");
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      this.sqlite.exec("COMMIT");
      return results;
    } catch (error) {
      this.sqlite.exec("ROLLBACK");
      throw error;
    }
  }
}

function seedRun(db, values = {}) {
  const now = "2026-08-10T00:00:00.000Z";
  const result = db.sqlite.prepare(`INSERT INTO pipeline_runs
    (execution_id,idempotency_key,trigger_type,status,stage,notification_status,
     notification_attempt_count,lease_expires_at,started_at,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)`).run(
      crypto.randomUUID(), `manual:${crypto.randomUUID()}`, "manual",
      values.status ?? "running", values.stage ?? "gemini",
      values.notification_status ?? "pending", values.notification_attempt_count ?? 0,
      values.lease_expires_at ?? "2026-08-09T00:00:00.000Z", now, now
    );
  return Number(result.lastInsertRowid);
}

function seedArticle(db, runId) {
  return Number(db.sqlite.prepare(`INSERT INTO curation_logs
    (source_type,llm_name,content,created_at,pipeline_run_id)
    VALUES ('test','test','private article','2026-08-10T00:00:00.000Z',?)`
  ).run(runId).lastInsertRowid);
}

function actionRequest(runId, action, evidence, operationKey = crypto.randomUUID()) {
  return new Request("https://example.test/pipeline-reconciliation", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Reconciliation-Key": operationKey },
    body: JSON.stringify({ runId, action, evidence })
  });
}

const runtime = { now: () => new Date("2026-08-10T12:00:00.000Z") };
assert.doesNotMatch(migrations[2], /\b(DROP|DELETE|UPDATE)\b/i);
assert.match(migrations[2], /operation_key TEXT NOT NULL UNIQUE/i);

{
  const db = new D1Sqlite();
  const runId = seedRun(db);
  const response = await handlePipelineReconciliationAction(
    actionRequest(runId, "mark_stale_failed", "Worker logs confirm execution ended before article save."), { DB: db }, runtime
  );
  assert.equal(response.status, 200);
  const run = db.sqlite.prepare("SELECT * FROM pipeline_runs WHERE id = ?").get(runId);
  assert.equal(run.status, "failed");
  assert.equal(run.error_code, "stale_run_reconciled_no_article");
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) count FROM pipeline_reconciliation_events").get().count, 1);
}

{
  const db = new D1Sqlite();
  const runId = seedRun(db);
  const articleId = seedArticle(db, runId);
  const response = await handlePipelineReconciliationAction(
    actionRequest(runId, "repair_saved_state", "D1 article exists and no Discord attempt was recorded."), { DB: db }, runtime
  );
  assert.equal(response.status, 200);
  const run = db.sqlite.prepare("SELECT * FROM pipeline_runs WHERE id = ?").get(runId);
  assert.equal(run.status, "saved");
  assert.equal(run.notification_status, "pending");
  assert.equal(run.article_id, articleId);
}

for (const [action, expectedStatus, expectedNotification] of [
  ["confirm_notification_delivered", "completed", "sent"],
  ["confirm_notification_not_delivered", "saved", "failed"]
]) {
  const db = new D1Sqlite();
  const runId = seedRun(db, { status: "saved", stage: "discord", notification_status: "sending", notification_attempt_count: 1 });
  seedArticle(db, runId);
  const response = await handlePipelineReconciliationAction(
    actionRequest(runId, action, "Discord audit evidence was checked by an authenticated operator."), { DB: db }, runtime
  );
  assert.equal(response.status, 200);
  const run = db.sqlite.prepare("SELECT * FROM pipeline_runs WHERE id = ?").get(runId);
  assert.equal(run.status, expectedStatus);
  assert.equal(run.notification_status, expectedNotification);
}

{
  const db = new D1Sqlite();
  const runId = seedRun(db, { status: "saved", stage: "discord", notification_status: "sending", notification_attempt_count: 1 });
  seedArticle(db, runId);
  const key = "same-operation";
  const first = await handlePipelineReconciliationAction(actionRequest(runId, "confirm_notification_delivered", "Discord message ID was verified in the destination channel.", key), { DB: db }, runtime);
  const second = await handlePipelineReconciliationAction(actionRequest(runId, "confirm_notification_delivered", "Discord message ID was verified in the destination channel.", key), { DB: db }, runtime);
  assert.equal(first.status, 200);
  assert.equal((await second.json()).status, "already_applied");
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) count FROM pipeline_reconciliation_events").get().count, 1);
}

{
  const db = new D1Sqlite();
  const runId = seedRun(db, { status: "saved", notification_status: "sending" });
  seedArticle(db, runId);
  const response = await handlePipelineReconciliationList({ DB: db }, runtime);
  const body = await response.json();
  assert.equal(body.runs[0].reconciliation_class, "delivery_unknown_human_review");
  assert.equal("content" in body.runs[0], false);
  assert.equal("idempotency_key" in body.runs[0], false);
}

assert.equal(classifyReconciliationRun({ status: "running", notification_status: "pending", has_article: 0, lease_expires_at: "2026-08-09T00:00:00.000Z" }, runtime.now()), "stale_without_article_can_fail");
assert.match(source, /notification_status === "sending"[\s\S]*notification_in_progress/);

{
  const env = { OPERATIONS_API_TOKEN: "valid-operations-token", DB: new D1Sqlite() };
  const unauthorized = await worker.fetch(new Request("https://example.test/pipeline-reconciliation"), env, {});
  const wrongMethod = await worker.fetch(new Request("https://example.test/pipeline-reconciliation", {
    method: "PUT", headers: { Authorization: "Bearer valid-operations-token" }
  }), env, {});
  assert.equal(unauthorized.status, 401);
  assert.equal(wrongMethod.status, 405);
}
console.log("step3 reconciliation tests passed");
