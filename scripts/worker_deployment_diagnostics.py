"""Safe, value-minimising parser for Cloudflare Workers Deployments responses."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class DeploymentShapeError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentTraffic:
    version_id: str
    percentage: float


@dataclass(frozen=True)
class LatestDeployment:
    version_count: int
    versions: tuple[DeploymentTraffic, ...]
    traffic_total: float


def parse_latest_deployment(payload: Mapping[str, Any]) -> LatestDeployment:
    """Parse only documented envelope.result.deployments[0].versions metadata."""
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise DeploymentShapeError("deployment_envelope_invalid")
    result = payload.get("result")
    if not isinstance(result, Mapping) or not isinstance(result.get("deployments"), list):
        raise DeploymentShapeError("deployment_list_invalid")
    deployments = result["deployments"]
    if not deployments or not isinstance(deployments[0], Mapping):
        raise DeploymentShapeError("latest_deployment_missing")
    versions = deployments[0].get("versions")
    if not isinstance(versions, list) or not versions:
        raise DeploymentShapeError("deployment_versions_invalid")
    safe: list[DeploymentTraffic] = []
    for item in versions:
        if not isinstance(item, Mapping) or not isinstance(item.get("version_id"), str) or not item["version_id"]:
            raise DeploymentShapeError("deployment_version_id_invalid")
        percentage = item.get("percentage")
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)) or percentage <= 0 or percentage > 100:
            raise DeploymentShapeError("deployment_percentage_invalid")
        safe.append(DeploymentTraffic(item["version_id"], float(percentage)))
    total = sum(item.percentage for item in safe)
    if abs(total - 100.0) > 1e-9:
        raise DeploymentShapeError("deployment_traffic_total_invalid")
    return LatestDeployment(len(safe), tuple(safe), total)
