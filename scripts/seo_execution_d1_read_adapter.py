"""Injected, fixed-SELECT boundary for future SEO execution D1 reads.

No token source, HTTP client, or write request exists in this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence
from d1_read_only_session import D1ReadSafetyError, validate_read_only_result_sets

ARTICLE_SQL = "SELECT id, title, description, category, content, body_markdown, published_at, updated_at, seo_status FROM curation_logs WHERE id=?"
MIGRATION_SQL = "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('seo_execution_attempts','seo_execution_attempt_events','seo_execution_post_verifications') ORDER BY name"
ATTEMPT_SQL = "SELECT execution_attempt_id, execution_approval_id, preflight_id, state, classification FROM seo_execution_attempts WHERE execution_approval_id=?"

class SeoExecutionReadAdapterError(ValueError): pass
@dataclass(frozen=True)
class ProductionD1Target:
    account_id: str
    database_id: str
    database_name: str
    environment: str = "production"
    def __post_init__(self):
        if not all(isinstance(x,str) and x for x in (self.account_id,self.database_id,self.database_name)) or self.environment != "production": raise SeoExecutionReadAdapterError("production_target_invalid")
class ReadTransport(Protocol):
    def identity(self) -> Mapping[str, Any]: ...
    def fixed_select_batch(self, statements: Sequence[Mapping[str, object]]) -> Mapping[str, Any]: ...

def _payload(value: Any) -> Mapping[str, Any]:
    data=getattr(value,"payload",value)
    if not isinstance(data,Mapping): raise SeoExecutionReadAdapterError("read_response_invalid")
    return data
def _rows(payload: Mapping[str, Any], count: int) -> list[Mapping[str,Any]]:
    try: sets=validate_read_only_result_sets(payload,count)
    except D1ReadSafetyError as e: raise SeoExecutionReadAdapterError("read_only_response_rejected") from e
    rows=[]
    for result in sets:
        result_rows=result.get("results")
        if not isinstance(result_rows,list) or not all(isinstance(x,Mapping) for x in result_rows): raise SeoExecutionReadAdapterError("read_rows_invalid")
        rows.append(result_rows)
    return rows
class SeoExecutionD1ReadAdapter:
    def __init__(self,target:ProductionD1Target,transport:ReadTransport): self.target,self.transport=target,transport
    def verify_identity(self)->None:
        result=_payload(self.transport.identity()).get("result")
        if not isinstance(result,Mapping) or result.get("name")!=self.target.database_name or result.get("uuid")!=self.target.database_id: raise SeoExecutionReadAdapterError("d1_identity_mismatch")
    def read_migration_preflight(self)->list[str]:
        self.verify_identity(); rows=_rows(_payload(self.transport.fixed_select_batch(({"sql":MIGRATION_SQL,"params":[]},))),1)[0]
        names=[x.get("name") for x in rows]
        if not all(isinstance(x,str) for x in names): raise SeoExecutionReadAdapterError("migration_preflight_invalid")
        return names
    def read_article_snapshot(self,article_id:int)->Mapping[str,Any]:
        if not isinstance(article_id,int) or article_id<1: raise SeoExecutionReadAdapterError("article_id_invalid")
        self.verify_identity(); rows=_rows(_payload(self.transport.fixed_select_batch(({"sql":ARTICLE_SQL,"params":[article_id]},))),1)[0]
        if len(rows)!=1 or rows[0].get("id")!=article_id: raise SeoExecutionReadAdapterError("article_snapshot_invalid")
        return rows[0]
    def read_approval_attempts(self,approval_id:str)->list[Mapping[str,Any]]:
        if not isinstance(approval_id,str) or not approval_id: raise SeoExecutionReadAdapterError("approval_id_invalid")
        self.verify_identity(); return _rows(_payload(self.transport.fixed_select_batch(({"sql":ATTEMPT_SQL,"params":[approval_id]},))),1)[0]
