// Inert local-only publication adapter; no Worker route imports it until deployment approval.
export const PUBLICATION_TRIGGER = "approved_canary_publication";
const required=["staging_draft_id","production_execution_id","production_input_id","publication_approval_id","quality_gate_audit_id","final_content_fingerprint"];
export async function runApprovedCanaryPublication({request,authorize,repository,notify}) {
 if(!request||request.trigger_type!==PUBLICATION_TRIGGER||required.some(k=>typeof request[k]!=="string"||!request[k]))throw new Error("publication_request_invalid");
 await authorize(request); const draft=await repository.readDraft(request.staging_draft_id); if(!draft||required.some(k=>draft[k]!==request[k]&&k!=="publication_approval_id"))throw new Error("publication_draft_mismatch");
 const execution=await repository.acquire(request,draft); await repository.transition(execution,"preflight_verified"); await repository.verifyApproval(request,draft); await repository.transition(execution,"approval_verified");
 await repository.transition(execution,"publish_started");
 try { const published=await repository.publishAtomically(execution,draft); if(!published.final_article_id)throw new Error("publication_outcome_unknown"); await repository.transition(execution,"published"); try { await notify(published); await repository.setNotification(execution,"notification_sent"); } catch { await repository.setNotification(execution,"notification_failed"); } return published; }
 catch { await repository.transition(execution,"publication_outcome_unknown"); throw new Error("publication_outcome_unknown"); }
}
