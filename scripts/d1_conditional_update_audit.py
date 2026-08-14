"""Fail-closed verification for a single-row conditional D1 UPDATE.

Cloudflare D1's ``rows_written`` includes index writes, so it is an audit
metric rather than a record-cardinality assertion.  The safe proof that one
table row changed is: ``changed_db is true``, SQLite ``changes == 1``, and an
``UPDATE ... RETURNING id`` result containing only the approved primary key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ConditionalUpdateAuditError(RuntimeError):
    """The D1 response cannot safely prove the approved one-row update."""


@dataclass(frozen=True)
class ConditionalUpdateAudit:
    changed_db: bool
    changes: int
    rows_written: int | None
    returned_id: int


def validate_exact_conditional_update(response: Mapping[str, Any], expected_id: int) -> ConditionalUpdateAudit:
    """Validate one D1 Query result without retaining response row content."""
    results = response.get("result")
    if response.get("success") is not True or not isinstance(results, list) or len(results) != 1:
        raise ConditionalUpdateAuditError("D1 conditional update response shape is invalid")
    item = results[0]
    if not isinstance(item, Mapping) or item.get("success") is not True:
        raise ConditionalUpdateAuditError("D1 conditional update result is unsuccessful")
    meta, rows = item.get("meta"), item.get("results")
    if not isinstance(meta, Mapping) or not isinstance(rows, list) or len(rows) != 1:
        raise ConditionalUpdateAuditError("D1 conditional update result is incomplete")
    changed_db, changes, rows_written = meta.get("changed_db"), meta.get("changes"), meta.get("rows_written")
    if changed_db is not True or changes != 1:
        raise ConditionalUpdateAuditError("D1 conditional update did not change exactly one table row")
    if rows_written is not None and (not isinstance(rows_written, int) or rows_written < 1):
        raise ConditionalUpdateAuditError("D1 conditional update write metadata is invalid")
    returned_id = rows[0].get("id") if isinstance(rows[0], Mapping) else None
    if returned_id != expected_id:
        raise ConditionalUpdateAuditError("D1 conditional update returned an unexpected row")
    return ConditionalUpdateAudit(changed_db, changes, rows_written, returned_id)
