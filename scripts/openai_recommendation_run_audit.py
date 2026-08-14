"""Crash-safe, value-free audit ledger for bounded OpenAI recommendation evals.

This module never loads an API key and never calls OpenAI.  A caller must create
and durably persist a ledger before it is allowed to send any request.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


AUDIT_SCHEMA_VERSION = "v2.0-a-openai-eval-run-audit-v1"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
ALLOWED_FINAL_STATES = frozenset({"result_known", "outcome_unknown"})


class AuditError(RuntimeError):
    """A fail-closed local audit error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise AuditError("run_id is invalid")


def build_request_plan(run_id: str, model_id: str, fixture_ids: Iterable[str]) -> list[dict[str, str]]:
    """Create deterministic, unique request IDs without prompt or response data."""
    _validate_run_id(run_id)
    if not isinstance(model_id, str) or not model_id.startswith("gpt-5.6-"):
        raise AuditError("model_id is invalid")
    plan, seen = [], set()
    for fixture_id in fixture_ids:
        if not isinstance(fixture_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", fixture_id):
            raise AuditError("fixture_id is invalid")
        client_request_id = f"{run_id}--{model_id}--{fixture_id}"
        if fixture_id in seen or len(client_request_id) > 512 or not client_request_id.isascii():
            raise AuditError("request plan is not unique")
        seen.add(fixture_id)
        plan.append({"model_id": model_id, "fixture_id": fixture_id, "client_request_id": client_request_id})
    if not plan:
        raise AuditError("request plan is empty")
    return plan


def _external_audit_path(audit_dir: str | Path, workspace: str | Path, run_id: str) -> Path:
    _validate_run_id(run_id)
    directory = Path(audit_dir).expanduser().resolve()
    root = Path(workspace).expanduser().resolve()
    if not directory.is_absolute() or directory == root or root in directory.parents:
        raise AuditError("audit directory must be absolute and outside the repository")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory / f"{run_id}.jsonl"


class RunAuditLedger:
    """Append-only audit state; values from prompts and model outputs are excluded."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id

    @classmethod
    def create(cls, audit_dir: str | Path, workspace: str | Path, run_id: str,
               plan: list[Mapping[str, str]]) -> "RunAuditLedger":
        path = _external_audit_path(audit_dir, workspace, run_id)
        normalized = []
        seen = set()
        for item in plan:
            model_id, fixture_id, client_request_id = item.get("model_id"), item.get("fixture_id"), item.get("client_request_id")
            if not all(isinstance(value, str) for value in (model_id, fixture_id, client_request_id)) or client_request_id in seen:
                raise AuditError("audit plan is invalid")
            seen.add(client_request_id)
            normalized.append({"model_id": model_id, "fixture_id": fixture_id, "client_request_id": client_request_id})
        if not normalized:
            raise AuditError("audit plan is empty")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": "manifest", "schema_version": AUDIT_SCHEMA_VERSION, "at": utc_now(),
                                         "run_id": run_id, "requests": normalized}, separators=(",", ":")) + "\n")
                handle.flush(); os.fsync(handle.fileno())
        except OSError as error:
            raise AuditError("audit ledger cannot be created") from error
        os.chmod(path, 0o600)
        return cls(path, run_id)

    def _append(self, event: Mapping[str, Any]) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                handle.flush(); os.fsync(handle.fileno())
            os.chmod(self.path, 0o600)
        except OSError as error:
            raise AuditError("audit ledger cannot be updated") from error

    def states(self) -> dict[str, str]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines]
        except (OSError, json.JSONDecodeError) as error:
            raise AuditError("audit ledger cannot be read") from error
        if not events or events[0].get("event") != "manifest" or events[0].get("run_id") != self.run_id:
            raise AuditError("audit ledger is invalid")
        states = {item["client_request_id"]: "planned" for item in events[0].get("requests", []) if isinstance(item, Mapping)}
        for event in events[1:]:
            request_id = event.get("client_request_id")
            if request_id not in states:
                raise AuditError("audit ledger request is invalid")
            if event.get("event") == "send_started":
                if states[request_id] != "planned":
                    raise AuditError("audit ledger has duplicate send")
                states[request_id] = "outcome_unknown"
            elif event.get("event") == "final" and event.get("state") in ALLOWED_FINAL_STATES:
                if states[request_id] != "outcome_unknown":
                    raise AuditError("audit ledger final state is invalid")
                states[request_id] = event["state"]
            else:
                raise AuditError("audit ledger event is invalid")
        return states

    def begin_request(self, client_request_id: str) -> None:
        states = self.states()
        if states.get(client_request_id) != "planned":
            raise AuditError("request is already sent or its outcome is unknown")
        self._append({"event": "send_started", "at": utc_now(), "run_id": self.run_id,
                      "client_request_id": client_request_id})

    def finalize(self, client_request_id: str, state: str, *, http_status: int | None,
                 classification: str, input_tokens: int = 0, output_tokens: int = 0,
                 server_request_id: str | None = None) -> None:
        if state not in ALLOWED_FINAL_STATES or self.states().get(client_request_id) != "outcome_unknown":
            raise AuditError("request finalization is invalid")
        if http_status is not None and (not isinstance(http_status, int) or not 100 <= http_status <= 599):
            raise AuditError("HTTP status is invalid")
        if not isinstance(classification, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", classification):
            raise AuditError("classification is invalid")
        if not all(isinstance(value, int) and value >= 0 for value in (input_tokens, output_tokens)):
            raise AuditError("token counts are invalid")
        if server_request_id is not None and (not isinstance(server_request_id, str) or not server_request_id.isascii() or len(server_request_id) > 512):
            raise AuditError("server request ID is invalid")
        self._append({"event": "final", "at": utc_now(), "run_id": self.run_id, "client_request_id": client_request_id,
                      "state": state, "http_status": http_status, "classification": classification,
                      "input_tokens": input_tokens, "output_tokens": output_tokens, "server_request_id": server_request_id})
