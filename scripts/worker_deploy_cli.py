"""Explicit, one-attempt CLI entrypoint for the safe Worker deploy wrapper.

This module deliberately contains no alternate deploy implementation: after its
local preflight it delegates the single subprocess decision to
``worker_deploy_wrapper.run_deploy``.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

from worker_deploy_wrapper import ACCOUNT, WRANGLER_VERSION, DeployAudit, run_deploy

ROOT = Path(__file__).parents[1].resolve()


def _safe_result(classification: str, audit: DeployAudit | None = None) -> dict[str, object]:
    result: dict[str, object] = {"classification": classification}
    if audit is not None:
        result["audit"] = {
            "process_started": audit.process_started,
            "build_stage_observed": audit.build_stage_observed,
            "upload_stage_observed": audit.upload_stage_observed,
            "cloudflare_response_observed": audit.cloudflare_response_observed,
            "exit_code": audit.exit_code,
            "timed_out": audit.timed_out,
            "interrupted": audit.interrupted,
            "classification": audit.classification,
            "argv_classification": audit.argv_classification,
            "cwd_classification": audit.cwd_classification,
            "config_discovery_classification": audit.config_discovery_classification,
            "child_environment_classification": audit.child_environment_classification,
            "stdin_managed": audit.stdin_managed,
            "build_stage_classification": audit.build_stage_classification,
            "dry_run_marker_observed": audit.dry_run_marker_observed,
            "autoconfig_aborted_observed": audit.autoconfig_aborted_observed,
            "opennext_delegation_observed": audit.opennext_delegation_observed,
            "config_redirect_observed": audit.config_redirect_observed,
        }
    return result


def _run(args: Sequence[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30, env=env)
    return completed.returncode, completed.stdout, completed.stderr


def _git_head(root: Path) -> str | None:
    code, output, _ = _run(("git", "rev-parse", "HEAD"), root)
    return output.strip() if code == 0 and output.strip() else None


def _tracked_clean(root: Path) -> bool:
    code, output, _ = _run(("git", "status", "--porcelain", "--untracked-files=no"), root)
    return code == 0 and not output.strip()


def _filesystem_ready(home: Path) -> bool:
    # These are the two runtime locations observed in Wrangler's own failure
    # diagnostics.  The probes leave no file behind.
    for directory in (home / ".wrangler" / "logs", home / ".Trash"):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".worker_deploy_cli_write_probe"
            probe.write_text("")
            probe.unlink()
        except OSError:
            return False
    return True


def _local_wrangler_version(root: Path) -> str | None:
    binary = root / "node_modules" / ".bin" / "wrangler"
    if not binary.exists():
        return None
    clean_env = {key: value for key, value in os.environ.items() if key != "CLOUDFLARE_API_TOKEN"}
    try:
        code, output, _ = _run(("npx", "--no-install", "wrangler", "--version"), root, clean_env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return output.strip().splitlines()[-1] if code == 0 and output.strip() else None


def _prompt_worker_token() -> str:
    return getpass.getpass("Worker token: ").strip()


def _deploy_runner(token: str, parent_env: Mapping[str, str] | None = None) -> Callable[[Sequence[str], Path], tuple[int, str, str]]:
    def runner(args: Sequence[str], cwd: Path) -> tuple[int, str, str]:
        # The official Wrangler token and fixed Account are supplied only to
        # this child.  Environment/profile selectors are removed so they
        # cannot silently change the Worker target or suppress safe markers.
        env = dict(parent_env if parent_env is not None else os.environ)
        for key in ("CLOUDFLARE_ENV", "CF_ACCOUNT_ID", "CF_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL", "CF_API_KEY", "CF_EMAIL"):
            env.pop(key, None)
        env.update({"CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT, "WRANGLER_LOG": "log", "WRANGLER_LOG_SANITIZE": "true"})
        completed = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, env=env)
        return completed.returncode, completed.stdout, completed.stderr
    return runner


def run_cli(
    argv: Sequence[str],
    *,
    root: Path = ROOT,
    cwd: Path | None = None,
    home: Path | None = None,
    token_provider: Callable[[], str] = _prompt_worker_token,
    git_head: Callable[[Path], str | None] = _git_head,
    tracked_clean: Callable[[Path], bool] = _tracked_clean,
    filesystem_ready: Callable[[Path], bool] = _filesystem_ready,
    version_getter: Callable[[Path], str | None] = _local_wrangler_version,
    deploy_function: Callable[..., DeployAudit] = run_deploy,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-account")
    parser.add_argument("--expected-wrangler-version")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        return _safe_result("invalid_arguments")
    actual_cwd = (cwd or Path.cwd()).resolve()
    actual_home = (home or Path.home()).resolve()
    parent_env = environment if environment is not None else os.environ
    root = root.resolve()
    if args.command != "deploy-once":
        return _safe_result("deploy_command_required")
    if actual_cwd != root:
        return _safe_result("repository_root_mismatch")
    if args.expected_account != ACCOUNT:
        return _safe_result("account_mismatch")
    if parent_env.get("CLOUDFLARE_ENV"):
        return _safe_result("unapproved_wrangler_environment")
    configured_account = parent_env.get("CLOUDFLARE_ACCOUNT_ID")
    if configured_account and configured_account != ACCOUNT:
        return _safe_result("account_environment_mismatch")
    if args.expected_wrangler_version != WRANGLER_VERSION:
        return _safe_result("wrangler_version_mismatch")
    # The caller must explicitly supply the human-approved commit; it is then
    # compared to the actual checkout before any subprocess can start.
    if not args.expected_head or git_head(root) != args.expected_head:
        return _safe_result("git_head_mismatch")
    if not tracked_clean(root):
        return _safe_result("tracked_worktree_dirty")
    if not filesystem_ready(actual_home):
        return _safe_result("filesystem_preflight_failed")
    if version_getter(root) != WRANGLER_VERSION:
        return _safe_result("wrangler_version_mismatch")

    token = token_provider().strip()
    if not token or token in {"{token}", "<token>", "WORKER_TOKEN"}:
        return _safe_result("worker_token_missing")
    try:
        audit = deploy_function(
            root=root,
            git_head=args.expected_head,
            account=args.expected_account,
            runner=_deploy_runner(token, parent_env),
            version_getter=lambda: version_getter(root) or "",
            child_environment_classification="approved_account_base_environment_log_sanitized",
            stdin_managed=True,
        )
    finally:
        token = ""
    if audit.classification == "deploy_succeeded":
        return _safe_result("deploy_succeeded_process_level", audit)
    if audit.timed_out or audit.interrupted or audit.classification in {"deploy_failed_after_upload", "process_succeeded_unobserved"}:
        return _safe_result("deploy_outcome_unknown", audit)
    return _safe_result(audit.classification, audit)


def main() -> int:
    # Only a JSON-safe classification is written; raw Wrangler streams are
    # deliberately discarded inside the existing wrapper.
    result = run_cli(sys.argv[1:])
    print(json.dumps(result, sort_keys=True))
    # A wrapper process can finish cleanly without an observable deployed
    # version. Make that ambiguity visible to the invoking human or script.
    return 2 if result["classification"] == "deploy_outcome_unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
