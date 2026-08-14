import importlib.util
import pathlib
import sys
import unittest


PATH = pathlib.Path(__file__).parents[1] / "scripts" / "d1_conditional_update_audit.py"
spec = importlib.util.spec_from_file_location("d1_conditional_update_audit", PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["d1_conditional_update_audit"] = module
spec.loader.exec_module(module)


def response(*, changed=True, changes=1, rows_written=3, returned_id=25):
    meta = {"changed_db": changed, "changes": changes}
    if rows_written != "omitted": meta["rows_written"] = rows_written
    return {"success": True, "result": [{"success": True, "meta": meta, "results": [{"id": returned_id}]}]}


class ConditionalUpdateAuditTest(unittest.TestCase):
    def test_changes_and_returning_id_prove_one_row_even_when_index_writes_raise_rows_written(self):
        audit = module.validate_exact_conditional_update(response(rows_written=3), 25)
        self.assertEqual((True, 1, 3, 25), (audit.changed_db, audit.changes, audit.rows_written, audit.returned_id))

    def test_rows_written_is_optional_but_never_used_as_record_cardinality(self):
        audit = module.validate_exact_conditional_update(response(rows_written="omitted"), 25)
        self.assertIsNone(audit.rows_written)

    def test_rejects_non_exact_change_or_returned_id(self):
        for values in ({"changed": False}, {"changes": 0}, {"changes": 2}, {"rows_written": 0}, {"returned_id": 26}):
            with self.assertRaises(module.ConditionalUpdateAuditError):
                module.validate_exact_conditional_update(response(**values), 25)

    def test_rejects_malformed_response(self):
        for bad in ({}, {"success": True, "result": []}, {"success": True, "result": [{"success": True, "meta": {"changed_db": True, "changes": 1}, "results": []}]}):
            with self.assertRaises(module.ConditionalUpdateAuditError):
                module.validate_exact_conditional_update(bad, 25)


if __name__ == "__main__":
    unittest.main()
