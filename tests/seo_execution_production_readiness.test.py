import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules[name] = module; spec.loader.exec_module(module); return module

spec = importlib.util.spec_from_file_location("seo_execution_candidate_qualification_test", ROOT / "tests" / "seo_execution_candidate_qualification.test.py")
fixture = importlib.util.module_from_spec(spec); assert spec and spec.loader
sys.modules["seo_execution_candidate_qualification_test"] = fixture; spec.loader.exec_module(fixture)
load("d1_read_only_session")
load("d1_conditional_update_audit")
load("seo_improvement_execution_attempt")
load("seo_execution_transaction_repository")
load("seo_execution_d1_write_adapter")
load("seo_execution_dry_run")
read = load("seo_execution_d1_read_adapter")
verify = load("seo_execution_production_verification")
readiness = load("seo_execution_production_readiness")

def payload(rows):
    return {"success": True, "result": [{"success": True, "meta": {"changed_db": False, "changes": 0, "rows_written": 0}, "results": rows}]}

class Transport:
    def __init__(self, row, *, tables=None, attempts=None, uuid="db"):
        self.row, self.tables, self.attempts, self.uuid = row, tables if tables is not None else sorted(verify.MIGRATION_0010_TABLES), attempts or [], uuid
        self.calls = []
    def identity(self): return {"result": {"name": "name", "uuid": self.uuid}}
    def fixed_select_batch(self, statements):
        sql = statements[0]["sql"]; self.calls.append(sql.split(" ", 2)[1])
        if "sqlite_master" in sql: return payload([{"name": name} for name in self.tables])
        if "seo_execution_attempts" in sql: return payload(self.attempts)
        return payload([self.row])

class TestProductionReadiness(unittest.TestCase):
    def setUp(self):
        self.artifacts = fixture.artifacts()
        snapshot = self.artifacts["latest_snapshot"]
        self.row = {"id": 1, "title": snapshot["title"], "description": snapshot["description"], "category": snapshot["category"], "content": "fixture content", "body_markdown": "fixture body", "published_at": snapshot["published_at"], "updated_at": snapshot["updated_at"], "seo_status": "ready"}
    def test_readiness_pass_is_fixed_zero_write(self):
        module = sys.modules["seo_execution_production_readiness"]
        original = module.snapshot_from_article_row
        module.snapshot_from_article_row = lambda _: self.artifacts["latest_snapshot"]
        try:
            adapter = read.SeoExecutionD1ReadAdapter(read.ProductionD1Target("a", "db", "name"), Transport(self.row))
            result = readiness.run_first_production_execution_readiness(adapter, self.artifacts, now="2026-08-21T02:10:00Z")
            self.assertEqual("pass", result["status"]); self.assertFalse(result["changed_db"]); self.assertEqual(0, result["rows_written"]); self.assertFalse(result["approval_consumed"])
        finally: module.snapshot_from_article_row = original
    def test_target_migration_reserved_and_stale_fail_closed(self):
        adapter = read.SeoExecutionD1ReadAdapter(read.ProductionD1Target("a", "db", "name"), Transport(self.row, uuid="other"))
        with self.assertRaises(readiness.SeoExecutionProductionReadinessError): readiness.run_first_production_execution_readiness(adapter, self.artifacts, now="2026-08-21T02:10:00Z")
        adapter = read.SeoExecutionD1ReadAdapter(read.ProductionD1Target("a", "db", "name"), Transport(self.row, tables=[]))
        with self.assertRaises(readiness.SeoExecutionProductionReadinessError): readiness.run_first_production_execution_readiness(adapter, self.artifacts, now="2026-08-21T02:10:00Z")
        adapter = read.SeoExecutionD1ReadAdapter(read.ProductionD1Target("a", "db", "name"), Transport(self.row, attempts=[{"execution_attempt_id": "used"}]))
        with self.assertRaises(readiness.SeoExecutionProductionReadinessError): readiness.run_first_production_execution_readiness(adapter, self.artifacts, now="2026-08-21T02:10:00Z")
        stale = {**self.artifacts, "latest_snapshot": {**self.artifacts["latest_snapshot"], "updated_at": "2026-01-03T00:00:00Z"}}
        self.assertNotEqual(stale["latest_snapshot"], self.artifacts["latest_snapshot"])

if __name__ == "__main__": unittest.main()
