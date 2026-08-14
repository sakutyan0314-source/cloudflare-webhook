import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py")); module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module

f = load("ai_improvement_cycle")
F = json.loads((ROOT / "tests" / "fixtures" / "v2f-improvement-cycle-fixture.json").read_text())

class ImprovementCycleTest(unittest.TestCase):
    def candidate(self, classification="neutral", history=(), **kwargs):
        measurement = dict(F["measurement"], measurement_classification=classification)
        if classification in {"measurement_pending", "insufficient_data", "contaminated", "classification_pending_threshold"}:
            measurement["threshold_status"] = "unapproved"
        return f.build_next_improvement_candidate(measurement, F["review"], prior_recommendation_type="improve_title", cause_code="low_ctr", history=history, now=F["now"], new_evidence=True, rollback_context=F["rollback_context"], **kwargs)

    def event(self, **kwargs):
        value = {"cycle_id": "cycle_old", "article_id": 25, "source_measurement_id": "measurement_old", "prior_recommendation_type": "improve_title", "cause_code": "low_ctr", "created_at": "2026-08-01T12:00:00Z", "state": "closed", "decision": "consider_new_recommendation", "measurement_started": True}
        value.update(kwargs); return value

    def test_accept_result_chain_and_deterministic_cycle_id(self):
        one, two = self.candidate(), self.candidate()
        self.assertEqual(one["cycle_id"], two["cycle_id"]); self.assertEqual("consider_new_recommendation", one["decision"]); self.assertFalse(one["execution_authorized"])
        bad = dict(F["review"], decision="hold")
        with self.assertRaises(f.CycleSafetyError): f.build_next_improvement_candidate(F["measurement"], bad, prior_recommendation_type="improve_title", cause_code="low_ctr", history=(), now=F["now"], new_evidence=True)
        with self.assertRaises(f.CycleSafetyError): self.candidate(history=[self.event(source_measurement_id="measurement_25_v1")])

    def test_classification_decisions_and_threshold_boundaries(self):
        self.assertEqual("continue_observation", self.candidate("improved")["decision"])
        self.assertEqual("hold", self.candidate("mixed_signal")["decision"])
        self.assertEqual("hold", self.candidate("classification_pending_threshold")["decision"])
        self.assertEqual("continue_observation", self.candidate("measurement_pending")["decision"])
        self.assertEqual("continue_observation", self.candidate("insufficient_data")["decision"])
        self.assertEqual("hold", self.candidate("contaminated")["decision"])
        worsened = self.candidate("worsened"); self.assertEqual("consider_rollback_review", worsened["decision"])
        self.assertFalse(f.build_rollback_candidate(worsened, F["rollback_context"])["rollback_authorized"])

    def test_cooldown_unresolved_and_rate_limits_are_safe(self):
        recent = self.event(created_at="2026-08-18T12:00:01Z")
        with self.assertRaisesRegex(f.CycleSafetyError, "cooldown_active"): self.candidate(history=[recent])
        with self.assertRaisesRegex(f.CycleSafetyError, "unresolved_cycle_exists"): self.candidate(history=[self.event(state="plan_pending", created_at="2026-07-01T00:00:00Z")])
        hourly = [self.event(cycle_id="cycle_hour", article_id=26, source_measurement_id="measurement_hour", cause_code="other", created_at="2026-09-01T11:30:00Z", measurement_started=False)]
        self.assertEqual("hold", self.candidate(history=hourly)["decision"])
        daily = [self.event(cycle_id="cycle_day"+str(i), article_id=26+i, source_measurement_id="measurement_day"+str(i), cause_code="other", created_at="2026-09-01T01:00:00Z", measurement_started=False) for i in range(3)]
        self.assertEqual("hold", self.candidate(history=daily)["decision"])

    def test_article_90_day_limit_and_v2a_reentry_need_human_review(self):
        history = [self.event(cycle_id="cycle_"+str(i), source_measurement_id="measurement_"+str(i), created_at="2026-08-0"+str(i+1)+"T00:00:00Z") for i in range(3)]
        self.assertEqual("hold", self.candidate(history=history)["decision"])
        candidate = self.candidate()
        handoff = f.build_v2a_reentry(candidate, {"cycle_id": candidate["cycle_id"], "decision": "approve", "execution_authorized": False})
        self.assertEqual(["v2.0-A", "v2.0-B", "v2.0-C", "v2.0-D", "v2.0-E"], handoff["required_chain"]); self.assertFalse(handoff["execution_authorized"])
        with self.assertRaises(f.CycleSafetyError): f.build_v2a_reentry(candidate, {"cycle_id": candidate["cycle_id"], "decision": "approve", "execution_authorized": True})

    def test_audit_is_protected_and_secrets_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = f.AppendOnlyCycleLedger(pathlib.Path(temporary)); ledger.append({"cycle_id": "cycle_25", "article_id": 25, "measurement_id": "measurement_25", "decision": "hold", "at": F["now"]})
            self.assertEqual(0o700, ledger.path.parent.stat().st_mode & 0o777); self.assertEqual(0o600, ledger.path.stat().st_mode & 0o777)
            with self.assertRaises(f.CycleSafetyError): ledger.append({"cycle_id": "cycle_25", "token": "forbidden"})

if __name__ == "__main__": unittest.main()
