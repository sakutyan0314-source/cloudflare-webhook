"""One-process, fail-closed v1.9.1 legacy SEO backfill runner.

This module intentionally contains no configured production endpoint.  A
future approved launcher supplies two transports: a Read transport and an Edit
transport.  The runner never accepts one transport for both roles, never
persists either token, and stops at the first unsafe article result.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
import getpass
import json
from pathlib import Path
import re
import signal
import subprocess
from typing import Any, Callable, Mapping, Protocol, Sequence

from d1_conditional_update_audit import ConditionalUpdateAudit, validate_exact_conditional_update
from d1_read_only_session import normalize_d1_read_token


BACKFILL_ORDER = (18, 19, 21, 23, 24, 27)
ALLOWED_CATEGORIES = frozenset({
    "ai-automation", "saas-cloud", "security-governance",
    "engineering-infrastructure", "dx-organization", "marketing-cx",
})
_EDIT_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")


class BackfillSafetyError(RuntimeError):
    """A precondition, response, or postcondition is unsafe."""


class OutcomeUnknownError(BackfillSafetyError):
    """The single UPDATE may have reached D1 but its outcome is unknown."""


def clear_system_clipboard() -> None:
    """Best-effort macOS clipboard clearing, without printing its contents."""
    try:
        subprocess.run(
            ["pbcopy"], input="", text=True, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        # Memory is still cleared by the caller. Clipboard failure is never
        # reported with token-bearing context.
        pass


@dataclass(frozen=True)
class ArticleResult:
    article_id: int
    changed_db: bool
    changes: int
    rows_written_reference: int | None
    returned_id: int


class ReadTransport(Protocol):
    """Read role only. Implementations must issue fixed SELECTs only."""

    role: str
    def read_article(self, article_id: int) -> Mapping[str, Any]: ...
    def foreign_key_check(self) -> int: ...
    def baseline(self) -> Mapping[str, int]: ...


class EditTransport(Protocol):
    """Edit role only. Implementations may send exactly one conditional UPDATE."""

    role: str
    def conditional_update(self, plan: Mapping[str, Any], content: str) -> Mapping[str, Any]: ...


class ReadTransportFactory(Protocol):
    """Creates only a read-role transport from the read token."""

    role: str
    def create_read_transport(self, token: str) -> ReadTransport: ...


class EditTransportFactory(Protocol):
    """Creates only an edit-role transport from the edit token."""

    role: str
    def create_edit_transport(self, token: str) -> EditTransport: ...


class InMemoryTokenPair(AbstractContextManager["InMemoryTokenPair"]):
    """Separate, non-repr token slots that are cleared on every exit path."""

    __slots__ = ("_read_token", "_edit_token", "_clear_clipboard", "_closed")

    def __init__(self, read_token: str, edit_token: str, clear_clipboard: Callable[[], None] = clear_system_clipboard) -> None:
        self._read_token = normalize_d1_read_token(read_token)
        normalized_edit = edit_token.strip(" \t\r\n") if isinstance(edit_token, str) else ""
        if not normalized_edit or any(ch.isspace() or ord(ch) < 32 for ch in normalized_edit) or not _EDIT_TOKEN.fullmatch(normalized_edit):
            raise BackfillSafetyError("D1 Edit token input is invalid")
        if normalized_edit == self._read_token:
            raise BackfillSafetyError("D1 Read and Edit tokens must be distinct")
        self._edit_token, self._clear_clipboard, self._closed = normalized_edit, clear_clipboard, False

    @classmethod
    def prompt_once(cls, clear_clipboard: Callable[[], None] = clear_system_clipboard) -> "InMemoryTokenPair":
        """Receive each token once without terminal echo or shell history."""
        return cls(getpass.getpass("D1 Read token: "), getpass.getpass("D1 Edit token: "), clear_clipboard)

    def __repr__(self) -> str:
        return "InMemoryTokenPair(<redacted>)"

    def read_token(self) -> str:
        if self._closed:
            raise BackfillSafetyError("token pair is closed")
        return self._read_token

    def edit_token(self) -> str:
        if self._closed:
            raise BackfillSafetyError("token pair is closed")
        return self._edit_token

    def close(self) -> None:
        if not self._closed:
            self._read_token = ""
            self._edit_token = ""
            self._closed = True
            self._clear_clipboard()

    def __exit__(self, *_: object) -> None:
        self.close()


def load_manifest(path: Path) -> dict[int, dict[str, Any]]:
    """Load exactly the approved six-article, fixed-effective_at manifest."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BackfillSafetyError("backfill manifest is invalid") from error
    if manifest.get("effective_at") != "2026-08-14T22:30:34.000Z" or manifest.get("target_ids") != list(BACKFILL_ORDER):
        raise BackfillSafetyError("backfill manifest identity is invalid")
    articles = manifest.get("articles")
    if not isinstance(articles, list) or [item.get("id") for item in articles if isinstance(item, Mapping)] != list(BACKFILL_ORDER):
        raise BackfillSafetyError("backfill manifest target order is invalid")
    output: dict[int, dict[str, Any]] = {}
    for item in articles:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), int):
            raise BackfillSafetyError("backfill manifest article is invalid")
        expected, target = item.get("expected"), item.get("target")
        if not isinstance(expected, Mapping) or not isinstance(target, Mapping):
            raise BackfillSafetyError("backfill manifest article is incomplete")
        if expected.get("seo_status") != "legacy" or expected.get("category") != "uncategorized" or any(expected.get(key) is not None for key in ("title", "description", "body_markdown", "published_at", "updated_at")):
            raise BackfillSafetyError("backfill manifest preconditions are unsafe")
        if target.get("category") not in ALLOWED_CATEGORIES or target.get("seo_status") != "ready" or target.get("updated_at") != manifest["effective_at"]:
            raise BackfillSafetyError("backfill manifest target is unsafe")
        if target.get("body_markdown_sha256") != expected.get("content_sha256"):
            raise BackfillSafetyError("backfill manifest body copy invariant is unsafe")
        if not isinstance(target.get("title"), str) or not 12 <= len(target["title"]) <= 120 or not isinstance(target.get("description"), str) or not 60 <= len(target["description"]) <= 160:
            raise BackfillSafetyError("backfill manifest metadata is invalid")
        expected_plan = dict(expected)
        # This is plan identity only; it is not an approved mutable field.
        expected_plan["id"] = item["id"]
        output[item["id"]] = {"expected": expected_plan, "target": dict(target)}
    return output


def validate_pre_update(article_id: int, row: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """Validate the current row before its sole permitted UPDATE attempt."""
    if not isinstance(row, Mapping) or row.get("id") != article_id or not isinstance(row.get("content"), str):
        raise BackfillSafetyError("pre_update_row_invalid")
    expected, target, content = plan["expected"], plan["target"], row["content"]
    for field in ("seo_status", "category", "title", "description", "body_markdown", "published_at", "updated_at"):
        if row.get(field) != expected[field]:
            raise BackfillSafetyError("stale_" + field)
    if sha256(content.encode("utf-8")).hexdigest() != expected["content_sha256"]:
        raise BackfillSafetyError("stale_content_sha256")
    if target["body_markdown_sha256"] != expected["content_sha256"]:
        raise BackfillSafetyError("body_copy_plan_mismatch")
    if not re.search(r"^#\s+\S", content, re.M) or not re.search(r"^##\s+\S", content, re.M):
        raise BackfillSafetyError("content_structure_mismatch")
    return content


def validate_post_update(article_id: int, row: Mapping[str, Any], plan: Mapping[str, Any], expected_content_sha: str) -> None:
    """Require exact approved metadata and unchanged body/content fingerprints."""
    if not isinstance(row, Mapping) or row.get("id") != article_id or not isinstance(row.get("content"), str) or not isinstance(row.get("body_markdown"), str):
        raise BackfillSafetyError("post_update_row_invalid")
    target = plan["target"]
    for field in ("seo_status", "category", "title", "description", "published_at", "updated_at"):
        if row.get(field) != target[field]:
            raise BackfillSafetyError("post_update_" + field + "_mismatch")
    content_sha = sha256(row["content"].encode("utf-8")).hexdigest()
    body_sha = sha256(row["body_markdown"].encode("utf-8")).hexdigest()
    if content_sha != expected_content_sha:
        raise BackfillSafetyError("post_update_content_sha_mismatch")
    if body_sha != content_sha:
        raise BackfillSafetyError("post_update_body_sha_mismatch")


class LegacyBackfillRunner:
    """Sequence 18→19→21→23→24→27 and stop permanently on first failure."""

    def __init__(self, read_transport: ReadTransport, edit_transport: EditTransport, plans: Mapping[int, Mapping[str, Any]]) -> None:
        if getattr(read_transport, "role", None) != "read" or getattr(edit_transport, "role", None) != "edit" or read_transport is edit_transport:
            raise BackfillSafetyError("Read/Edit transport roles must be separated")
        self._read, self._edit, self._plans = read_transport, edit_transport, dict(plans)
        self._sent: set[int] = set()

    def run(self, expected_baseline: Mapping[str, int]) -> list[ArticleResult]:
        output: list[ArticleResult] = []
        for article_id in BACKFILL_ORDER:
            if article_id in self._sent:
                raise BackfillSafetyError("duplicate_update_attempt")
            plan = self._plans.get(article_id)
            if not isinstance(plan, Mapping):
                raise BackfillSafetyError("missing_article_plan")
            current = self._read.read_article(article_id)
            content = validate_pre_update(article_id, current, plan)
            self._sent.add(article_id)  # reserve before transport; no retry after any ambiguous result
            try:
                response = self._edit.conditional_update(plan, content)
            except OutcomeUnknownError:
                raise
            except Exception as error:
                raise BackfillSafetyError("update_transport_failed") from error
            try:
                audit: ConditionalUpdateAudit = validate_exact_conditional_update(response, article_id)
            except Exception as error:
                raise BackfillSafetyError("update_result_invalid") from error
            after = self._read.read_article(article_id)
            validate_post_update(article_id, after, plan, plan["expected"]["content_sha256"])
            if self._read.foreign_key_check() != 0:
                raise BackfillSafetyError("foreign_key_check_failed")
            if dict(self._read.baseline()) != dict(expected_baseline):
                raise BackfillSafetyError("non_target_state_changed")
            output.append(ArticleResult(article_id, audit.changed_db, audit.changes, audit.rows_written, audit.returned_id))
        return output


def run_with_in_memory_tokens(tokens: InMemoryTokenPair, runner: LegacyBackfillRunner, expected_baseline: Mapping[str, int]) -> list[ArticleResult]:
    """Ensure token cleanup also occurs for SIGINT/SystemExit/ordinary failure."""
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(_signum: int, _frame: object) -> None: raise SystemExit("SIGTERM")
    signal.signal(signal.SIGTERM, terminate)
    try:
        with tokens:
            # Token objects are intentionally not passed into audit output or plans.
            tokens.read_token(); tokens.edit_token()
            return runner.run(expected_baseline)
    finally:
        signal.signal(signal.SIGTERM, previous)
        tokens.close()


def run_backfill_session(
    tokens: InMemoryTokenPair,
    read_factory: ReadTransportFactory,
    edit_factory: EditTransportFactory,
    plans: Mapping[int, Mapping[str, Any]],
    expected_baseline: Mapping[str, int],
) -> list[ArticleResult]:
    """Bind each in-memory token to its sole permitted transport role.

    This is the only supported token-to-transport binding point.  It makes a
    read transport unavailable to the edit factory and vice versa; future
    network transport implementations must be supplied separately.
    """
    with tokens:
        if getattr(read_factory, "role", None) != "read" or getattr(edit_factory, "role", None) != "edit" or read_factory is edit_factory:
            raise BackfillSafetyError("Read/Edit transport factory roles must be separated")
        read_transport = read_factory.create_read_transport(tokens.read_token())
        edit_transport = edit_factory.create_edit_transport(tokens.edit_token())
        runner = LegacyBackfillRunner(read_transport, edit_transport, plans)
        return run_with_in_memory_tokens(tokens, runner, expected_baseline)
