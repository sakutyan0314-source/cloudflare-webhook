"""Manual-only operator boundary; production execution is intentionally absent."""
from __future__ import annotations
from typing import Any
from seo_execution_dry_run import run_dry_run
class SeoExecutionOperatorError(ValueError): pass
def run_operator_dry_run(*args:Any,**kwargs:Any)->dict[str,Any]: return run_dry_run(*args,**kwargs)
def run_production_execution(*_:Any,**__:Any)->None: raise SeoExecutionOperatorError("production_execution_not_implemented")
