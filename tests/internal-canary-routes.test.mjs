import assert from "node:assert/strict";
import fs from "node:fs/promises";

const root = new URL("../", import.meta.url);
const publication = await fs.readFile(new URL("src/publication_worker_adapter.js", root), "utf8");
let source = await fs.readFile(new URL("src/index.ts", root), "utf8");
source = source.replaceAll('"./publication_worker_adapter.js"', `"data:text/javascript;base64,${Buffer.from(publication).toString("base64")}"`);
const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const worker = module.default;
const token = "route-test-token";
const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
let calls = [];
const env = {
  SITE_URL: "https://local.test",
  OPERATIONS_API_TOKEN: token,
  APPROVED_CANARY_PUBLICATION_RUNTIME: { resolve: async (payload) => ({ request: payload, repository: { readDraft: async () => ({ ...payload }), acquire: async () => "e", transition: async () => {}, verifyApproval: async () => {}, publishAtomically: async () => ({ final_article_id: 99 }), setNotification: async () => {} }, notify: async () => calls.push("notify") }) }
};
async function request(path, options = {}) { return worker.fetch(new Request(`https://local.test${path}`, options), env, {}); }
const production = { trigger_type: "approved_canary", production_input_id: "input", approval_id: "approval", production_execution_id: "execution", pipeline_run_id: 1 };
const publicationPayload = { trigger_type: "approved_canary_publication", staging_draft_id: "draft", production_execution_id: "execution", production_input_id: "input", publication_approval_id: "approval", quality_gate_audit_id: "audit", final_content_fingerprint: "fingerprint" };
let n = 0; async function test(name, fn) { await fn(); n++; console.log(`ok ${n} - ${name}`); }
await test("authenticated canary POST without a D1 bundle fails before any adapter", async () => { calls=[]; const r=await request("/internal/approved-canary", { method:"POST", headers, body:JSON.stringify(production) }); assert.notEqual(r.status,202); assert.deepEqual(calls,[]); });
await test("publication endpoint is separate and authenticated", async () => { calls=[]; const r=await request("/internal/approved-canary/publication", { method:"POST", headers, body:JSON.stringify(publicationPayload) }); assert.equal(r.status,202); assert.deepEqual(calls,["notify"]); });
await test("GET, unauthenticated, malformed, oversized and unknown fields do not reach adapters", async () => { calls=[]; for (const options of [{},{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"},{method:"POST",headers,body:"{"},{method:"POST",headers,body:JSON.stringify({...production,topic:"arbitrary"})},{method:"POST",headers,body:"x".repeat(17000)}]) { const r=await request("/internal/approved-canary",options); assert.notEqual(r.status,202); } assert.deepEqual(calls,[]); });
await test("production entry requires a positive integer pipeline run ID", async () => { calls=[]; for (const payload of [{...production,pipeline_run_id:undefined},{...production,pipeline_run_id:0},{...production,pipeline_run_id:"1"}]) { const r=await request("/internal/approved-canary",{method:"POST",headers,body:JSON.stringify(payload)}); assert.notEqual(r.status,202); } assert.deepEqual(calls,[]); });
await test("public and cron routes remain separate", async () => { assert.equal((await request("/robots.txt")).status,200); assert.equal((await request("/internal/approved-canary",{method:"GET"})).status,405); assert.match(source,/runScheduledPipeline\(env, \{\}, event\.scheduledTime\)/); });
assert.match(source,/async scheduled\(event, env, ctx\) \{\s*ctx\.waitUntil\(runScheduledPipeline\(env, \{\}, event\.scheduledTime\)\);/);
console.log("internal canary route tests passed");
