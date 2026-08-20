"""Non-connected fixed-SQL builder for future SEO execution D1 writes.

It deliberately exposes no transport, token, or execute method.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from seo_execution_transaction_repository import build_conditional_snippet_update

class SeoExecutionWriteAdapterError(ValueError): pass
class ProductionD1WriteDisabled(SeoExecutionWriteAdapterError): pass
_PREFIXES=("INSERT INTO seo_execution_attempts ","INSERT INTO seo_execution_attempt_events ","UPDATE seo_execution_attempts SET ","INSERT INTO seo_execution_post_verifications ","UPDATE curation_logs SET ")
def validate_fixed_write(statement:Mapping[str,Any])->None:
    sql=statement.get("sql") if isinstance(statement,Mapping) else None; params=statement.get("params") if isinstance(statement,Mapping) else None
    if not isinstance(sql,str) or not isinstance(params,Sequence) or isinstance(params,(str,bytes)) or ";" in sql or not sql.startswith(_PREFIXES): raise SeoExecutionWriteAdapterError("write_sql_not_whitelisted")
    if sql.startswith("UPDATE curation_logs SET ") and ("RETURNING id" not in sql or "content=?" not in sql or "body_markdown=?" not in sql or "body_markdown=?" in sql.split(" WHERE ",1)[0]): raise SeoExecutionWriteAdapterError("snippet_update_shape_invalid")
def build_conditional_update_statement(candidate:Mapping[str,Any],current_row:Mapping[str,Any])->dict[str,Any]:
    result=build_conditional_snippet_update(candidate,current_row); statement={"sql":result["sql"],"params":result["params"]};validate_fixed_write(statement);return {**statement,"expected_article_id":result["expected_article_id"],"set_fields":result["set_fields"]}
def execution_disabled(*_:Any,**__:Any)->None: raise ProductionD1WriteDisabled("production_d1_write_not_connected")
