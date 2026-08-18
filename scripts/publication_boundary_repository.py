"""Local SQLite publication boundary for approved-canary drafts only.

Drafts are intentionally stored outside curation_logs.  This module has no
network, Worker, AI, D1 transport, or Discord dependency.
"""
from __future__ import annotations
from datetime import datetime
from hashlib import sha256
import json, sqlite3
from typing import Any, Mapping

DRAFT_SCHEMA_VERSION="content-staging-draft-v1"; FINGERPRINT_SCHEMA_VERSION="publication-content-fingerprint-v1"; APPROVAL_SCHEMA_VERSION="content-publication-approval-v1"; EXECUTION_SCHEMA_VERSION="approved-canary-publication-execution-v1"
STATES=frozenset({"planned","preflight_verified","approval_verified","publish_started","published","publication_outcome_unknown"}); TERMINAL=frozenset({"published","publication_outcome_unknown"}); TRANSITIONS={"planned":frozenset({"preflight_verified"}),"preflight_verified":frozenset({"approval_verified"}),"approval_verified":frozenset({"publish_started"}),"publish_started":frozenset({"published","publication_outcome_unknown"})}; REASONS=frozenset({"publication_approval_missing","publication_approval_expired","publication_approval_mismatch","content_fingerprint_mismatch","quality_gate_not_passed","duplicate_publication","concurrent_publication","publication_state_conflict","curation_insert_failed","publication_outcome_unknown","notification_not_eligible"}); CATEGORIES=frozenset({"ai-automation","saas-cloud","security-governance","engineering-infrastructure","dx-organization","marketing-cx"})
FORBIDDEN=frozenset({"prompt","production_brief","raw_response","raw_ai_response","token","secret","authorization","api_key"})
class PublicationSafetyError(ValueError): pass
class PublicationDuplicateError(PublicationSafetyError): pass
class PublicationStateConflict(PublicationSafetyError): pass

def _json(value: Any)->str:return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _time(value: Any):
 if not isinstance(value,str) or not value.endswith("Z"):raise PublicationSafetyError("timestamp_invalid")
 try:return datetime.fromisoformat(value.replace("Z","+00:00"))
 except ValueError as error:raise PublicationSafetyError("timestamp_invalid") from error
def _reject(value: Any)->None:
 if isinstance(value,Mapping):
  for key,child in value.items():
   if not isinstance(key,str) or key.casefold() in FORBIDDEN: raise PublicationSafetyError("forbidden_publication_metadata")
   _reject(child)
 elif isinstance(value,(list,tuple)):
  for child in value:_reject(child)
def _id(prefix:str,identity:Mapping[str,Any])->str:return prefix+sha256(_json(identity).encode()).hexdigest()[:24]
def final_content_fingerprint(*,content:str,title:str,description:str,body_markdown:str,category:str,published_at_candidate:str|None,updated_at_candidate:str|None,seo_status:str="ready")->str:
 values={"fingerprint_schema_version":FINGERPRINT_SCHEMA_VERSION,"content":content,"title":title,"description":description,"body_markdown":body_markdown,"category":category,"published_at_candidate":published_at_candidate,"updated_at_candidate":updated_at_candidate,"seo_status":seo_status}; _reject(values)
 if not all(isinstance(values[k],str) and values[k] for k in ("content","title","description","body_markdown")) or category not in CATEGORIES or seo_status!="ready":raise PublicationSafetyError("content_fingerprint_input_invalid")
 return "final_content_"+sha256(_json(values).encode()).hexdigest()
def deterministic_publication_approval_id(*,staging_draft_id:str,production_execution_id:str,production_input_id:str,quality_gate_audit_id:str,final_content_fingerprint_value:str,approved_by:str,approved_at:str,expires_at:str)->str:
 return _id("publication_approval_",{"schema_version":APPROVAL_SCHEMA_VERSION,"staging_draft_id":staging_draft_id,"production_execution_id":production_execution_id,"production_input_id":production_input_id,"quality_gate_audit_id":quality_gate_audit_id,"final_content_fingerprint":final_content_fingerprint_value,"approved_by":approved_by,"approved_at":approved_at,"expires_at":expires_at,"single_use":True})
def deterministic_publication_execution_id(*,staging_draft_id:str,publication_approval_id:str)->str:return _id("publication_execution_",{"schema_version":EXECUTION_SCHEMA_VERSION,"staging_draft_id":staging_draft_id,"publication_approval_id":publication_approval_id})
def _event_id(execution_id:str,sequence:int,to_state:str,occurred_at:str)->str:return _id("publication_event_",{"execution_id":execution_id,"sequence":sequence,"to_state":to_state,"occurred_at":occurred_at})
def _row(cursor):
 value=cursor.fetchone();return dict(value) if value else None

def build_publication_approval(draft:Mapping[str,Any],*,approved_by:str,approved_at:str,expires_at:str,max_ttl_seconds:int|None=None)->dict[str,Any]:
 approved,expires=_time(approved_at),_time(expires_at)
 if not isinstance(approved_by,str) or not approved_by or expires<=approved:raise PublicationSafetyError("publication_approval_time_invalid")
 if max_ttl_seconds is not None and (not isinstance(max_ttl_seconds,int) or max_ttl_seconds<1 or (expires-approved).total_seconds()>max_ttl_seconds):raise PublicationSafetyError("publication_approval_ttl_invalid")
 output={"schema_version":APPROVAL_SCHEMA_VERSION,"publication_approval_id":deterministic_publication_approval_id(staging_draft_id=draft["staging_draft_id"],production_execution_id=draft["production_execution_id"],production_input_id=draft["production_input_id"],quality_gate_audit_id=draft["quality_gate_audit_id"],final_content_fingerprint_value=draft["final_content_fingerprint"],approved_by=approved_by,approved_at=approved_at,expires_at=expires_at),"staging_draft_id":draft["staging_draft_id"],"production_execution_id":draft["production_execution_id"],"production_input_id":draft["production_input_id"],"topic_candidate_id":draft["topic_candidate_id"],"quality_gate_audit_id":draft["quality_gate_audit_id"],"final_content_fingerprint":draft["final_content_fingerprint"],"approved_by":approved_by,"approved_at":approved_at,"expires_at":expires_at,"single_use":True,"publication_authorized":True}
 return output

class PublicationBoundaryRepository:
 def __init__(self,connection:sqlite3.Connection,*,fail_event_insert:bool=False,fail_curation_insert:bool=False):self.connection=connection;self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON");self.fail_event_insert=fail_event_insert;self.fail_curation_insert=fail_curation_insert
 def create_staging_draft(self,*,staging_draft_id:str,production_execution_id:str,production_input_id:str,topic_candidate_id:str,quality_gate_audit_id:str,content:str,title:str,description:str,body_markdown:str,category:str,published_at_candidate:str|None,updated_at_candidate:str|None,created_at:str)->dict[str,Any]:
  fp=final_content_fingerprint(content=content,title=title,description=description,body_markdown=body_markdown,category=category,published_at_candidate=published_at_candidate,updated_at_candidate=updated_at_candidate)
  quality=_row(self.connection.execute("SELECT classification FROM quality_gate_audits WHERE audit_id=?",(quality_gate_audit_id,)))
  if quality is None or quality["classification"]!="pass":raise PublicationSafetyError("quality_gate_not_passed")
  values=(staging_draft_id,DRAFT_SCHEMA_VERSION,production_execution_id,production_input_id,topic_candidate_id,quality_gate_audit_id,fp,FINGERPRINT_SCHEMA_VERSION,"pass",content,title,description,body_markdown,category,"ready",published_at_candidate,updated_at_candidate,created_at)
  try:
   with self.connection:self.connection.execute("INSERT INTO content_staging_drafts (staging_draft_id,schema_version,production_execution_id,production_input_id,topic_candidate_id,quality_gate_audit_id,final_content_fingerprint,fingerprint_schema_version,seo_quality_classification,publication_status,content,title,description,body_markdown,category,seo_status,published_at_candidate,updated_at_candidate,created_at) VALUES (?,?,?,?,?,?,?,?,?,'publication_pending',?,?,?,?,?,?,?,?,?)",values)
  except sqlite3.IntegrityError as error:raise PublicationDuplicateError("staging_draft_duplicate") from error
  return self.draft(staging_draft_id) or self._missing()
 def draft(self,staging_draft_id:str)->dict[str,Any]|None:return _row(self.connection.execute("SELECT * FROM content_staging_drafts WHERE staging_draft_id=?",(staging_draft_id,)))
 def build_approval(self,draft:Mapping[str,Any],**kwargs):return build_publication_approval(draft,**kwargs)
 def _validate_approval(self,approval:Mapping[str,Any],draft:Mapping[str,Any],now:str):
  _reject(approval);required={"schema_version","publication_approval_id","staging_draft_id","production_execution_id","production_input_id","topic_candidate_id","quality_gate_audit_id","final_content_fingerprint","approved_by","approved_at","expires_at","single_use","publication_authorized"}
  if set(approval)!=required or approval.get("schema_version")!=APPROVAL_SCHEMA_VERSION or approval.get("single_use") is not True or approval.get("publication_authorized") is not True or _time(now)>_time(approval.get("expires_at")):raise PublicationSafetyError("publication_approval_invalid_or_expired")
  for key in ("staging_draft_id","production_execution_id","production_input_id","topic_candidate_id","quality_gate_audit_id","final_content_fingerprint"):
   if approval.get(key)!=draft.get(key):raise PublicationSafetyError("publication_approval_mismatch")
  expected=deterministic_publication_approval_id(staging_draft_id=draft["staging_draft_id"],production_execution_id=draft["production_execution_id"],production_input_id=draft["production_input_id"],quality_gate_audit_id=draft["quality_gate_audit_id"],final_content_fingerprint_value=draft["final_content_fingerprint"],approved_by=approval["approved_by"],approved_at=approval["approved_at"],expires_at=approval["expires_at"])
  if approval.get("publication_approval_id")!=expected:raise PublicationSafetyError("publication_approval_mismatch")
 def acquire(self,*,draft:Mapping[str,Any],approval:Mapping[str,Any],now:str)->dict[str,Any]:
  self._validate_approval(approval,draft,now); execution_id=deterministic_publication_execution_id(staging_draft_id=draft["staging_draft_id"],publication_approval_id=approval["publication_approval_id"]);event=_event_id(execution_id,0,"planned",now)
  try:
   with self.connection:
    self.connection.execute("INSERT INTO publication_executions (publication_execution_id,schema_version,staging_draft_id,production_execution_id,publication_approval_id,final_content_fingerprint,state,state_version,notification_classification,created_at) VALUES (?,?,?,?,?,?,'planned',0,'not_applicable',?)",(execution_id,EXECUTION_SCHEMA_VERSION,draft["staging_draft_id"],draft["production_execution_id"],approval["publication_approval_id"],draft["final_content_fingerprint"],now))
    if self.fail_event_insert:raise sqlite3.IntegrityError("injected event")
    self.connection.execute("INSERT INTO publication_execution_events (event_id,publication_execution_id,event_sequence,from_state,to_state,occurred_at) VALUES (?, ?,0,NULL,'planned',?)",(event,execution_id,now))
  except sqlite3.IntegrityError as error:raise PublicationDuplicateError("publication_execution_duplicate") from error
  return self.execution(execution_id) or self._missing()
 def transition(self,*,execution_id:str,expected_state:str,expected_version:int,to_state:str,now:str,classification:str|None=None,reason_code:str|None=None)->dict[str,Any]:
  if to_state not in TRANSITIONS.get(expected_state,()) or (classification is not None and classification not in {"published","outcome_unknown"}) or (reason_code is not None and reason_code not in REASONS):raise PublicationStateConflict("publication_transition_rejected")
  if to_state=="published" and classification!="published" or to_state=="publication_outcome_unknown" and classification!="outcome_unknown":raise PublicationStateConflict("publication_classification_invalid")
  version=expected_version+1; event=_event_id(execution_id,version,to_state,now)
  try:
   with self.connection:
    cur=self.connection.execute("UPDATE publication_executions SET state=?,classification=?,state_version=?,publish_started_at=CASE WHEN ?='publish_started' THEN ? ELSE publish_started_at END,completed_at=CASE WHEN ? IN ('published','publication_outcome_unknown') THEN ? ELSE completed_at END WHERE publication_execution_id=? AND state=? AND state_version=?",(to_state,classification,version,to_state,now,to_state,now,execution_id,expected_state,expected_version))
    if cur.rowcount!=1:raise PublicationStateConflict("publication_cas_conflict")
    if self.fail_event_insert:raise sqlite3.IntegrityError("injected event")
    self.connection.execute("INSERT INTO publication_execution_events (event_id,publication_execution_id,event_sequence,from_state,to_state,classification,reason_code,occurred_at) VALUES (?,?,?,?,?,?,?,?)",(event,execution_id,version,expected_state,to_state,classification,reason_code,now))
  except sqlite3.IntegrityError as error:raise PublicationStateConflict("publication_snapshot_event_atomicity_failed") from error
  return self.execution(execution_id) or self._missing()
 def publish_atomically(self,*,execution_id:str,expected_version:int,now:str)->dict[str,Any]:
  execution=self.execution(execution_id)
  if not execution or execution["state"]!="approval_verified" or execution["state_version"]!=expected_version:raise PublicationStateConflict("publication_cas_conflict")
  draft=self.draft(execution["staging_draft_id"])
  if not draft or draft["publication_status"]!="publication_pending" or draft["final_content_fingerprint"]!=execution["final_content_fingerprint"]:raise PublicationSafetyError("content_fingerprint_mismatch")
  quality=_row(self.connection.execute("SELECT classification FROM quality_gate_audits WHERE audit_id=?",(draft["quality_gate_audit_id"],)))
  if quality is None or quality["classification"]!="pass":raise PublicationSafetyError("quality_gate_not_passed")
  recalculated=final_content_fingerprint(content=draft["content"],title=draft["title"],description=draft["description"],body_markdown=draft["body_markdown"],category=draft["category"],published_at_candidate=draft["published_at_candidate"],updated_at_candidate=draft["updated_at_candidate"])
  if recalculated!=execution["final_content_fingerprint"]:raise PublicationSafetyError("content_fingerprint_mismatch")
  try:
   with self.connection:
    started=self.connection.execute("UPDATE publication_executions SET state='publish_started',state_version=?,publish_started_at=? WHERE publication_execution_id=? AND state='approval_verified' AND state_version=?",(expected_version+1,now,execution_id,expected_version))
    if started.rowcount!=1:raise PublicationStateConflict("publication_cas_conflict")
    self.connection.execute("INSERT INTO publication_execution_events (event_id,publication_execution_id,event_sequence,from_state,to_state,occurred_at) VALUES (?,?,?,?,?,?)",(_event_id(execution_id,expected_version+1,"publish_started",now),execution_id,expected_version+1,"approval_verified","publish_started",now))
    if self.fail_curation_insert:raise sqlite3.IntegrityError("injected curation")
    pipeline=_row(self.connection.execute("SELECT pipeline_run_id FROM production_executions WHERE production_execution_id=?",(draft["production_execution_id"],)))
    cur=self.connection.execute("INSERT INTO curation_logs (source_type,llm_name,content,created_at,pipeline_run_id,title,description,body_markdown,category,published_at,updated_at,seo_status) VALUES ('approved_canary_staging','Approved Canary Production',?,?,?,?,?,?,?,?,?,?)",(draft["content"],now,pipeline["pipeline_run_id"] if pipeline else None,draft["title"],draft["description"],draft["body_markdown"],draft["category"],draft["published_at_candidate"],draft["updated_at_candidate"],draft["seo_status"]))
    article_id=cur.lastrowid
    finished=self.connection.execute("UPDATE publication_executions SET state='published',classification='published',state_version=?,completed_at=?,final_article_id=?,notification_classification='eligible' WHERE publication_execution_id=? AND state='publish_started' AND state_version=?",(expected_version+2,now,article_id,execution_id,expected_version+1))
    if finished.rowcount!=1:raise PublicationStateConflict("publication_cas_conflict")
    self.connection.execute("UPDATE content_staging_drafts SET publication_status='published' WHERE staging_draft_id=? AND publication_status='publication_pending'",(draft["staging_draft_id"],))
    if self.fail_event_insert:raise sqlite3.IntegrityError("injected event")
    self.connection.execute("INSERT INTO publication_execution_events (event_id,publication_execution_id,event_sequence,from_state,to_state,classification,occurred_at) VALUES (?,?,?,?,?,?,?)",(_event_id(execution_id,expected_version+2,"published",now),execution_id,expected_version+2,"publish_started","published","published",now))
  except sqlite3.IntegrityError as error:raise PublicationStateConflict("curation_insert_or_atomicity_failed") from error
  return self.execution(execution_id) or self._missing()
 def execution(self,execution_id):return _row(self.connection.execute("SELECT * FROM publication_executions WHERE publication_execution_id=?",(execution_id,)))
 def events(self,execution_id):return [dict(x) for x in self.connection.execute("SELECT * FROM publication_execution_events WHERE publication_execution_id=? ORDER BY event_sequence",(execution_id,))]
 def draft_count(self):return int(self.connection.execute("SELECT COUNT(*) FROM content_staging_drafts").fetchone()[0])
 def pending_count(self):return int(self.connection.execute("SELECT COUNT(*) FROM content_staging_drafts WHERE publication_status='publication_pending'").fetchone()[0])
 def rejected_count(self):return int(self.connection.execute("SELECT COUNT(*) FROM content_staging_drafts WHERE publication_status='rejected'").fetchone()[0])
 def state_counts(self):return {x["state"]:int(x["n"]) for x in self.connection.execute("SELECT state,COUNT(*) n FROM publication_executions GROUP BY state")}
 def published_count(self):return int(self.connection.execute("SELECT COUNT(*) FROM publication_executions WHERE state='published'").fetchone()[0])
 def unknown_count(self):return int(self.connection.execute("SELECT COUNT(*) FROM publication_executions WHERE state='publication_outcome_unknown'").fetchone()[0])
 def approval_consumed(self,publication_approval_id:str)->bool:return self.connection.execute("SELECT 1 FROM publication_executions WHERE publication_approval_id=?",(publication_approval_id,)).fetchone() is not None
 def final_article_id(self,execution_id:str)->int|None:
  row=_row(self.connection.execute("SELECT final_article_id FROM publication_executions WHERE publication_execution_id=?",(execution_id,)));return int(row["final_article_id"]) if row and row["final_article_id"] is not None else None
 def notification_classification(self,execution_id:str)->str|None:
  row=_row(self.connection.execute("SELECT notification_classification FROM publication_executions WHERE publication_execution_id=?",(execution_id,)));return str(row["notification_classification"]) if row else None
 def links(self):return [dict(x) for x in self.connection.execute("SELECT production_execution_id,staging_draft_id,final_article_id,notification_classification FROM publication_executions")]
 @staticmethod
 def _missing():raise PublicationSafetyError("publication_read_after_write_failed")
