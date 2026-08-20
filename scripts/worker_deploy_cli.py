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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from worker_deploy_wrapper import ACCOUNT, WRANGLER_VERSION, WRANGLER_CLI_RELATIVE_PATH, DeployAudit, run_deploy
from worker_deployment_diagnostics import DeploymentShapeError, LatestDeployment, parse_latest_deployment

ROOT = Path(__file__).parents[1].resolve()


def _deployment_outcome(classification: str) -> str:
    """Separate remote deployment evidence from the local process result."""
    if classification == "deploy_succeeded_verified":
        return "succeeded"
    if classification in {"deploy_failed_before_upload", "deploy_confirmation_required", "deploy_confirmation_declined_or_aborted"}:
        return "failed"
    if classification.startswith(("preflight_", "git_", "account_", "wrangler_", "repository_", "filesystem_", "worker_token_", "deploy_command_")):
        return "not_attempted"
    return "unknown"


def _safe_result(classification: str, audit: DeployAudit | None = None, postcheck: Mapping[str, object] | None = None) -> dict[str, object]:
    result: dict[str, object] = {"classification": classification, "deployment_outcome": _deployment_outcome(classification)}
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
            "version_marker_observed": audit.version_marker_observed,
            "signal_terminated": audit.signal_terminated,
            "error_classification": audit.error_classification,
            "process_result": audit.process_result,
        }
    if postcheck is not None:
        result["post_deploy_check"] = dict(postcheck)
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
    entrypoint = root / WRANGLER_CLI_RELATIVE_PATH
    if not entrypoint.is_file():
        return None
    clean_env = {key: value for key, value in os.environ.items() if key != "CLOUDFLARE_API_TOKEN"}
    try:
        code, output, _ = _run(("node", "--no-warnings", str(entrypoint), "--version"), root, clean_env)
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


def _fetch_latest_deployment(token: str) -> LatestDeployment:
    """Perform exactly one GET and retain no response text outside this call."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/cloudflare-webhook/deployments"
    request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, UnicodeError):
        raise DeploymentShapeError("deployment_postcheck_unavailable") from None
    return parse_latest_deployment(payload)


def _verify_post_deploy(pre_deploy_version: str, latest: LatestDeployment) -> dict[str, object]:
    """Compare value-free deployment metadata without persisting IDs or JSON."""
    traffic_expected = latest.version_count == 1 and latest.traffic_total == 100.0 and latest.versions[0].percentage == 100.0
    version_changed = latest.versions[0].version_id != pre_deploy_version
    return {"attempted": True, "succeeded": True, "version_changed": version_changed, "traffic_expected": traffic_expected, "classification": "post_deploy_verified" if version_changed and traffic_expected else "post_deploy_state_mismatch"}


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
    post_deploy_fetcher: Callable[[str], LatestDeployment] = _fetch_latest_deployment,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-account")
    parser.add_argument("--expected-wrangler-version")
    parser.add_argument("--pre-deploy-version")
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
    if not args.pre_deploy_version:
        return _safe_result("pre_deploy_version_required")
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
        if audit.classification != "deploy_succeeded":
            if audit.timed_out or audit.interrupted or audit.signal_terminated or audit.classification in {"deploy_failed_after_upload", "process_succeeded_unobserved", "process_signal_terminated"}:
                return _safe_result("deploy_outcome_unknown", audit)
            return _safe_result(audit.classification, audit)
        try:
            postcheck = _verify_post_deploy(args.pre_deploy_version, post_deploy_fetcher(token))
        except (DeploymentShapeError, OSError, ValueError):
            return _safe_result("deploy_outcome_unknown", audit, {"attempted": True, "succeeded": False, "version_changed": False, "traffic_expected": False, "classification": "post_deploy_check_unavailable"})
        if postcheck["classification"] != "post_deploy_verified":
            return _safe_result("deploy_outcome_unknown", audit, postcheck)
        return _safe_result("deploy_succeeded_verified", audit, postcheck)
    finally:
        token = ""


def main() -> int:
    # Only a JSON-safe classification is written; raw Wrangler streams are
    # deliberately discarded inside the existing wrapper.
    result = run_cli(sys.argv[1:])
    print(json.dumps(result, sort_keys=True))
    # A wrapper process can finish cleanly without an observable deployed
    # version. Make that ambiguity visible to the invoking human or script.
    outcome = result.get("deployment_outcome", _deployment_outcome(str(result.get("classification", ""))))
    return 0 if outcome == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
