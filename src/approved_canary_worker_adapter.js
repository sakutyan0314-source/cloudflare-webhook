// Inert local Worker adapter. No route imports this module until a separately approved deploy.
export const APPROVED_CANARY_TRIGGER = "approved_canary";
export const APPROVED_CANARY_MAX_ATTEMPTS = 1;
const forbidden = new Set(["prompt", "content", "body_markdown", "raw_response", "token", "authorization", "secret"]);
function rejectSensitive(value) { if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) { if (forbidden.has(key.toLowerCase())) throw new Error("canary_sensitive_input_rejected"); rejectSensitive(child); } }
export function buildApprovedCanaryGeminiInstruction(brief) {
  rejectSensitive(brief);
  const required = ["production_input_id","topic_candidate_id","human_review_id","topic","title_hint","primary_intent","target_audience","problem_to_solve","cluster_id","internal_link_guidance"];
  if (!brief || required.some((key) => !(key in brief)) || ["ai_generation_authorized","publication_authorized","execution_authorized"].some((key) => brief[key] !== false)) throw new Error("canary_brief_invalid");
  return `テーマ: ${brief.topic}\nタイトル案: ${brief.title_hint}\n検索意図: ${brief.primary_intent}\n対象読者: ${brief.target_audience}\n解決課題: ${brief.problem_to_solve}\nクラスター: ${brief.cluster_id}\n内部リンク方針: ${JSON.stringify(brief.internal_link_guidance)}`;
}
export async function runApprovedCanaryWorker({ request, authorize, validate, executionRepository, pipeline, qualityGate, staging }) {
  if (!request || request.trigger_type !== APPROVED_CANARY_TRIGGER || Object.keys(request).some((key) => !["trigger_type","production_input","approval","production_execution_id","pipeline_run_id","brief"].includes(key))) throw new Error("canary_request_invalid");
  await authorize(request); await validate(request);
  const execution = await executionRepository.acquire(request);
  await executionRepository.transition(execution, "preflight_verified"); await executionRepository.linkPipelineRun(execution, request.pipeline_run_id); await executionRepository.transition(execution, "approval_verified");
  await executionRepository.transition(execution, "send_started");
  try {
    const article = await pipeline({ triggerType: APPROVED_CANARY_TRIGGER, maxAttempts: APPROVED_CANARY_MAX_ATTEMPTS, geminiInstruction: buildApprovedCanaryGeminiInstruction(request.brief) });
    const audit = await qualityGate(article); if (audit.classification !== "pass") return executionRepository.transition(execution, "outcome_known_failed");
    await executionRepository.linkQualityGateAudit(execution, audit.audit_id); await staging.create({ execution, audit, article });
    return executionRepository.transition(execution, "outcome_known_success");
  } catch (error) { return executionRepository.transition(execution, "outcome_unknown"); }
}
