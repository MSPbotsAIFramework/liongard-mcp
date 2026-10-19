# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tool discovery, kept for compatibility: every tool is always listed."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact as to_json
from ._common import LOCAL, ClientFactory

DOMAINS: dict[str, tuple[str, list[str]]] = {
    "environments": (
        "Environments (customers): list, get, create, count, related entities.",
        ["liongard_environments_list", "liongard_environments_get", "liongard_environments_create", "liongard_environments_count", "liongard_environments_related"],
    ),
    "agents": ("Liongard agents that run inspections.", ["liongard_agents_list", "liongard_agents_delete"]),
    "inspections": (
        "Inspectors (integration types) and launchpoints (configured inspections).",
        ["liongard_inspections_inspectors", "liongard_inspections_launchpoints", "liongard_inspections_create_launchpoint", "liongard_inspections_run"],
    ),
    "systems": ("Inspected systems and their latest data.", ["liongard_systems_list", "liongard_systems_get"]),
    "detections": ("Changes found between inspections.", ["liongard_detections_list", "liongard_detections_get"]),
    "metrics": ("Named values computed from system data.", ["liongard_metrics_list", "liongard_metrics_evaluate", "liongard_metrics_evaluate_systems"]),
    "timeline": ("Inspection run history.", ["liongard_timeline_list"]),
    "inventory": (
        "Asset inventory: identities (users) and device profiles.",
        ["liongard_inventory_identities", "liongard_inventory_identity_get", "liongard_inventory_devices", "liongard_inventory_device_get"],
    ),
}

Domain = Literal["environments", "agents", "inspections", "systems", "detections", "metrics", "timeline", "inventory"]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def liongard_navigate(domain: Annotated[Domain, Field(description="Area to describe.")]) -> str:
        """Describe the tools of one Liongard area. All tools are already callable; this changes nothing."""
        summary, tools = DOMAINS[domain]
        return to_json({"domain": domain, "summary": summary, "tools": tools})
