// Production D1 resolver for immutable, content-free approved-canary bundles.
// It deliberately has no fallback, retry, publication override, or Cron entrypoint.
const SCHEMA = "approved-content-production-authorization-bundle-v1";
const FORBIDDEN = new Set(["content", "body_markdown", "prompt", "token", "secret", "authorization", "api_key", "raw_response"]);

export class ApprovedCanaryRuntimeError extends Error {}

function rejectForbidden(value) {
  if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN.has(key.toLowerCase())) throw new ApprovedCanaryRuntimeError("bundle_forbidden_field");
    rejectForbidden(child);
  }
}
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
async function digest(value) {
  const bytes = new TextEncoder().encode(canonical(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return "authorization_bundle_" + [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
function parseSnapshot(value) {
  if (typeof value !== "string") throw new ApprovedCanaryRuntimeError("bundle_snapshot_invalid");
  try {
    const parsed = JSON.parse(value);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
    rejectForbidden(parsed); return parsed;
  } catch { throw new ApprovedCanaryRuntimeError("bundle_snapshot_invalid"); }
}
function requiredString(value, key) {
  if (typeof value?.[key] !== "string" || !value[key]) throw new ApprovedCanaryRuntimeError("bundle_identity_invalid");
  return value[key];
}
function requireFalse(value, keys) {
  if (keys.some((key) => value?.[key] !== false)) throw new ApprovedCanaryRuntimeError("bundle_authorization_invalid");
}
function parseRow(row) {
  if (!row || row.schema_version !== SCHEMA || Number(row.single_use) !== 1) throw new ApprovedCanaryRuntimeError("bundle_schema_invalid");
  const snapshots = {
    candidate: parseSnapshot(row.candidate_snapshot_json), review: parseSnapshot(row.review_snapshot_json),
    approvedPlanning: parseSnapshot(row.approved_planning_snapshot_json), handoff: parseSnapshot(row.content_handoff_snapshot_json),
    productionInput: parseSnapshot(row.production_input_snapshot_json), approval: parseSnapshot(row.approval_snapshot_json),
  };
  const { candidate, review, approvedPlanning, handoff, productionInput, approval } = snapshots;
  requireFalse(candidate, ["content_generation_authorized", "publication_authorized", "execution_authorized"]);
  requireFalse(review, ["content_generation_authorized", "publication_authorized", "execution_authorized"]);
  requireFalse(approvedPlanning, ["content_generation_authorized", "publication_authorized", "execution_authorized"]);
  requireFalse(handoff, ["ai_generation_authorized", "publication_authorized", "execution_authorized"]);
  requireFalse(productionInput, ["ai_generation_authorized", "publication_authorized", "execution_authorized"]);
  if (candidate.candidate_status !== "pending_human_review" || review.decision !== "approve_for_content_planning" || approval.single_use !== true || approval.ai_generation_authorized !== true || approval.publication_authorized !== false || approval.execution_authorized !== true) throw new ApprovedCanaryRuntimeError("bundle_chain_invalid");
  const expected = {
    topic_candidate_id: requiredString(candidate, "topic_candidate_id"), review_id: requiredString(review, "review_id"),
    production_input_id: requiredString(productionInput, "production_input_id"), production_approval_id: requiredString(approval, "approval_id"),
  };
  if (Object.entries(expected).some(([key, value]) => row[key] !== value) || row.cluster_id !== productionInput.cluster || review.topic_candidate_id !== candidate.topic_candidate_id || approvedPlanning.topic_candidate_id !== candidate.topic_candidate_id || handoff.topic_candidate_id !== candidate.topic_candidate_id || productionInput.topic_candidate_id !== candidate.topic_candidate_id || approval.topic_candidate_id !== candidate.topic_candidate_id || productionInput.human_review_id !== review.review_id || approval.human_review_id !== review.review_id || approval.production_input_id !== productionInput.production_input_id || handoff.handoff_id !== productionInput.source_handoff_id) throw new ApprovedCanaryRuntimeError("bundle_identity_invalid");
  return { ...snapshots, expected };
}
function bundleIdentity(row, snapshots) {
  return {
    schema_version: row.schema_version, topic_candidate_id: row.topic_candidate_id, review_id: row.review_id,
    production_input_id: row.production_input_id, production_approval_id: row.production_approval_id,
    production_execution_id: row.production_execution_id, cluster_id: row.cluster_id,
    approved_at: row.approved_at, expires_at: row.expires_at, single_use: true,
    candidate_snapshot: snapshots.candidate, review_snapshot: snapshots.review,
    approved_planning_snapshot: snapshots.approvedPlanning, content_handoff_snapshot: snapshots.handoff,
    production_input_snapshot: snapshots.productionInput, approval_snapshot: snapshots.approval,
  };
}
export async function resolveApprovedCanaryBundle(db, payload, now = new Date()) {
  if (!db || !payload || payload.trigger_type !== "approved_canary") throw new ApprovedCanaryRuntimeError("canary_request_invalid");
  const row = await db.prepare("SELECT * FROM approved_content_authorization_bundles WHERE production_input_id=? AND production_approval_id=? LIMIT 1").bind(payload.production_input_id, payload.approval_id).first();
  if (!row) throw new ApprovedCanaryRuntimeError("canary_bundle_missing");
  const snapshots = parseRow(row);
  if (payload.production_execution_id !== row.production_execution_id) throw new ApprovedCanaryRuntimeError("canary_execution_identity_invalid");
  if (Date.parse(row.expires_at) <= now.getTime() || row.approved_at !== snapshots.approval.approved_at || row.expires_at !== snapshots.approval.expires_at) throw new ApprovedCanaryRuntimeError("canary_approval_expired");
  if (await digest(bundleIdentity(row, snapshots)) !== row.bundle_fingerprint) throw new ApprovedCanaryRuntimeError("canary_bundle_fingerprint_invalid");
  const used = await db.prepare("SELECT production_execution_id FROM production_executions WHERE production_input_id=? OR approval_id=? LIMIT 1").bind(row.production_input_id, row.production_approval_id).first();
  if (used) throw new ApprovedCanaryRuntimeError("canary_single_use_consumed");
  const brief = {
    production_input_id: row.production_input_id, topic_candidate_id: row.topic_candidate_id, human_review_id: row.review_id,
    topic: snapshots.productionInput.topic, title_hint: snapshots.productionInput.title_hint,
    primary_intent: snapshots.productionInput.primary_intent, target_audience: snapshots.productionInput.target_audience,
    problem_to_solve: snapshots.productionInput.problem_to_solve, cluster_id: snapshots.productionInput.cluster,
    internal_link_guidance: snapshots.productionInput.internal_link_guidance,
    ai_generation_authorized: false, publication_authorized: false, execution_authorized: false,
  };
  return { row, brief, specification: { triggerType: "manual", idempotencyKey: `manual:topic:${row.production_input_id}`, scheduledFor: null, sourceType: "approved_topic_candidate", discordHeader: null, topicAwareBrief: brief } };
}
export async function reserveApprovedCanary(db, resolved, occurredAt) {
  const row = resolved.row;
  const eventId = `production_event_${crypto.randomUUID()}`;
  const statements = [
    db.prepare("INSERT INTO production_executions (production_execution_id,schema_version,production_input_id,production_input_fingerprint,approval_id,topic_candidate_id,human_review_id,trigger_type,state,classification,state_version,notification_classification,publication_authorized,created_at) VALUES (?,?,?,?,?,?,?,?, 'planned',NULL,0,'not_applicable',0,?)").bind(row.production_execution_id, "approved-canary-production-execution-v1", row.production_input_id, JSON.parse(row.approval_snapshot_json).production_input_fingerprint, row.production_approval_id, row.topic_candidate_id, row.review_id, "approved_canary", occurredAt),
    db.prepare("INSERT INTO production_execution_events (event_id,production_execution_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?, ?, 0, NULL, 'planned', NULL, NULL, ?)").bind(eventId, row.production_execution_id, occurredAt),
  ];
  try { await db.batch(statements); } catch { throw new ApprovedCanaryRuntimeError("canary_single_use_reservation_failed"); }
  for (const [sequence, from, to] of [[1, "planned", "preflight_verified"], [2, "preflight_verified", "approval_verified"], [3, "approval_verified", "send_started"]]) {
    const event = `production_event_${crypto.randomUUID()}`;
    const result = await db.batch([
      db.prepare("UPDATE production_executions SET state=?, state_version=?, started_at=CASE WHEN ?='preflight_verified' THEN ? ELSE started_at END, send_started_at=CASE WHEN ?='send_started' THEN ? ELSE send_started_at END WHERE production_execution_id=? AND state=? AND state_version=?").bind(to, sequence, to, occurredAt, to, occurredAt, row.production_execution_id, from, sequence - 1),
      db.prepare("INSERT INTO production_execution_events (event_id,production_execution_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)").bind(event, row.production_execution_id, sequence, from, to, occurredAt),
    ]);
    if (!result) throw new ApprovedCanaryRuntimeError("canary_state_reservation_failed");
  }
}

export async function finalizeApprovedCanary(db, resolved, { result, occurredAt }) {
  const row = resolved.row;
  const pipeline = await db.prepare("SELECT id,article_id FROM pipeline_runs WHERE idempotency_key=? LIMIT 1").bind(resolved.specification.idempotencyKey).first();
  const audit = pipeline ? await db.prepare("SELECT audit_id,classification FROM quality_gate_audits WHERE pipeline_run_id=? ORDER BY evaluated_at DESC LIMIT 1").bind(pipeline.id).first() : null;
  const success = result?.outcome === "completed" && Number.isInteger(pipeline?.article_id) && audit?.classification === "pass";
  const state = success ? "outcome_known_success" : "outcome_known_failed";
  const classification = success ? "success" : "known_failure";
  const reason = success ? null : "transport_known_failure";
  const event = `production_event_${crypto.randomUUID()}`;
  await db.batch([
    db.prepare("UPDATE production_executions SET state=?,classification=?,state_version=4,completed_at=?,pipeline_run_id=?,final_article_id=?,quality_gate_audit_id=? WHERE production_execution_id=? AND state='send_started' AND state_version=3").bind(state, classification, occurredAt, pipeline?.id ?? null, pipeline?.article_id ?? null, audit?.classification === "pass" ? audit.audit_id : null, row.production_execution_id),
    db.prepare("INSERT INTO production_execution_events (event_id,production_execution_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?, ?, 4, 'send_started', ?, ?, ?, ?)").bind(event, row.production_execution_id, state, classification, reason, occurredAt),
  ]);
  return { state, classification, pipelineRunId: pipeline?.id ?? null, articleId: pipeline?.article_id ?? null, qualityGateAuditId: audit?.audit_id ?? null };
}

export async function recordApprovedCanaryOutcomeUnknown(db, resolved, occurredAt) {
  const event = `production_event_${crypto.randomUUID()}`;
  await db.batch([
    db.prepare("UPDATE production_executions SET state='outcome_unknown',classification='outcome_unknown',state_version=4,completed_at=? WHERE production_execution_id=? AND state='send_started' AND state_version=3").bind(occurredAt, resolved.row.production_execution_id),
    db.prepare("INSERT INTO production_execution_events (event_id,production_execution_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?, ?, 4, 'send_started', 'outcome_unknown', 'outcome_unknown', 'outcome_unknown_requires_review', ?)").bind(event, resolved.row.production_execution_id, occurredAt),
  ]);
}
