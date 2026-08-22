import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import fs from "node:fs/promises";

globalThis.crypto ??= webcrypto;
const source = await fs.readFile(new URL("../src/approved_content_authorization_bundle_runtime.js", import.meta.url), "utf8");
const runtime = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
async function fingerprint(identity) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(identity)));
  return "authorization_bundle_" + [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
async function row({ expired = false, used = false, tamper = false } = {}) {
  const candidate={topic_candidate_id:"topic_one",candidate_status:"pending_human_review",content_generation_authorized:false,publication_authorized:false,execution_authorized:false};
  const review={review_id:"review_one",topic_candidate_id:"topic_one",decision:"approve_for_content_planning",content_generation_authorized:false,publication_authorized:false,execution_authorized:false};
  const approvedPlanning={topic_candidate_id:"topic_one",content_generation_authorized:false,publication_authorized:false,execution_authorized:false};
  const handoff={handoff_id:"handoff_one",topic_candidate_id:"topic_one",human_review_id:"review_one",ai_generation_authorized:false,publication_authorized:false,execution_authorized:false};
  const productionInput={production_input_id:"input_one",source_handoff_id:"handoff_one",topic_candidate_id:"topic_one",human_review_id:"review_one",topic:"topic",title_hint:"hint",primary_intent:"how",target_audience:"audience",problem_to_solve:"problem",cluster:"ai-agent-foundation",internal_link_guidance:{},ai_generation_authorized:false,publication_authorized:false,execution_authorized:false};
  const approval={approval_id:"approval_one",production_input_id:"input_one",production_input_fingerprint:"input_fp",topic_candidate_id:"topic_one",human_review_id:"review_one",approved_at:"2026-08-22T18:00:00.000Z",expires_at:expired?"2026-08-22T18:30:00.000Z":"2026-08-22T20:00:00.000Z",single_use:true,ai_generation_authorized:true,publication_authorized:false,execution_authorized:true};
  const result={schema_version:"approved-content-production-authorization-bundle-v1",authorization_bundle_id:"bundle_one",topic_candidate_id:"topic_one",review_id:"review_one",production_input_id:"input_one",production_approval_id:"approval_one",production_execution_id:"execution_one",cluster_id:"ai-agent-foundation",approved_at:approval.approved_at,expires_at:approval.expires_at,single_use:1,candidate_snapshot_json:JSON.stringify(candidate),review_snapshot_json:JSON.stringify(review),approved_planning_snapshot_json:JSON.stringify(approvedPlanning),content_handoff_snapshot_json:JSON.stringify(handoff),production_input_snapshot_json:JSON.stringify(productionInput),approval_snapshot_json:JSON.stringify(approval),created_at:"2026-08-22T18:00:00.000Z"};
  result.bundle_fingerprint=await fingerprint({schema_version:result.schema_version,topic_candidate_id:result.topic_candidate_id,review_id:result.review_id,production_input_id:result.production_input_id,production_approval_id:result.production_approval_id,production_execution_id:result.production_execution_id,cluster_id:result.cluster_id,approved_at:result.approved_at,expires_at:result.expires_at,single_use:true,candidate_snapshot:candidate,review_snapshot:review,approved_planning_snapshot:approvedPlanning,content_handoff_snapshot:handoff,production_input_snapshot:productionInput,approval_snapshot:approval});
  if(tamper) result.cluster_id="saas-post-saas";
  return {result,used};
}
function dbFor(item) { return { prepare(sql) { return { bind() { return { first: async () => sql.includes("approved_content_authorization_bundles") ? item.result : (item.used ? {production_execution_id:"old"} : null) }; } }; } }; }
const payload={trigger_type:"approved_canary",production_input_id:"input_one",approval_id:"approval_one",production_execution_id:"execution_one",pipeline_run_id:1};
let n=0; async function test(name, fn){await fn();n++;console.log(`ok ${n} - ${name}`);}
await test("valid immutable bundle resolves to topic-aware brief",async()=>{const item=await row();const out=await runtime.resolveApprovedCanaryBundle(dbFor(item),payload,new Date("2026-08-22T19:00:00.000Z"));assert.equal(out.brief.topic,"topic");assert.equal(out.specification.idempotencyKey,"manual:topic:input_one");});
await test("expired approval fails before pipeline",async()=>{const item=await row({expired:true});await assert.rejects(runtime.resolveApprovedCanaryBundle(dbFor(item),payload,new Date("2026-08-22T19:00:00.000Z")));});
await test("fingerprint tampering fails before pipeline",async()=>{const item=await row({tamper:true});await assert.rejects(runtime.resolveApprovedCanaryBundle(dbFor(item),payload,new Date("2026-08-22T19:00:00.000Z")));});
await test("used production input fails before pipeline",async()=>{const item=await row({used:true});await assert.rejects(runtime.resolveApprovedCanaryBundle(dbFor(item),payload,new Date("2026-08-22T19:00:00.000Z")));});
await test("missing bundle fails before pipeline",async()=>{const item={result:null,used:false};await assert.rejects(runtime.resolveApprovedCanaryBundle(dbFor(item),payload,new Date("2026-08-22T19:00:00.000Z")));});
