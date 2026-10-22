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
"""Inspectors (integration types) and launchpoints (an inspector configured for an environment)."""

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient
from ._common import READ_ONLY, WRITES, ClientFactory, Offset, Page, PageSize, compact, local_page, run_tool


def schedule(value: str | None) -> tuple[str, int]:
    """'daily' / 'day' / 'every 6 hours' / '12h' / '2 days' -> (FreqType, FreqInterval); default daily."""
    if not value or not value.strip():
        return "day", 1
    text = value.strip().lower()
    if text in ("daily", "day"):
        return "day", 1
    if text in ("hourly", "hour"):
        return "hour", 1
    match = re.fullmatch(r"(?:every\s+)?(\d+)\s*(h|hr|hrs|hour|hours|d|day|days)", text)
    if not match:
        raise ValueError("Schedule must look like 'daily', 'hourly', 'every 6 hours' or '2 days'.")
    return ("hour" if match.group(2).startswith("h") else "day"), int(match.group(1))


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inspections_inspectors(page: Page = None, pageSize: PageSize = None, offset: Offset = None) -> str:
        """List inspectors (integration types such as Microsoft 365, Active Directory, firewalls) with ids."""

        async def action(client: LiongardClient) -> dict:
            return local_page(await client.get("v1", "inspectors"), "inspectors", page, pageSize, offset)

        return await run_tool("liongard_inspections_inspectors", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inspections_launchpoints(page: Page = None, pageSize: PageSize = None, offset: Offset = None) -> str:
        """List launchpoints: inspector, environment, agent, schedule, last run and status."""

        async def action(client: LiongardClient) -> dict:
            return local_page(await client.get("v1", "launchpoints"), "launchpoints", page, pageSize, offset)

        return await run_tool("liongard_inspections_launchpoints", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def liongard_inspections_create_launchpoint(
        Name: Annotated[str, Field(description="Launchpoint name (its alias), e.g. 'Microsoft 365 - Example Co'.", min_length=1)],
        InspectorID: Annotated[int, Field(description="Inspector id (liongard_inspections_inspectors).", ge=1)],
        EnvironmentID: Annotated[int, Field(description="Environment id.", ge=1)],
        AgentID: Annotated[int | None, Field(description="Agent that runs it (liongard_agents_list); required by Liongard.", ge=1)] = None,
        Schedule: Annotated[str | None, Field(description="'daily' (default), 'hourly', 'every 6 hours', '2 days'.")] = None,
        Config: Annotated[dict[str, Any] | None, Field(description="Inspector configuration (URLs, tenant ids ...), per the inspector's template.")] = None,
        SecureConfig: Annotated[dict[str, Any] | None, Field(description="Inspector secrets (passwords, tokens), per the inspector's template.")] = None,
    ) -> str:
        """Create a launchpoint: run an inspector for an environment on a schedule. Only when explicitly asked."""

        async def action(client: LiongardClient) -> Any:
            if AgentID is None:
                raise ValueError("Pass AgentID: Liongard needs the agent that will run the inspection (see liongard_agents_list).")
            freq_type, interval = schedule(Schedule)
            body = compact(
                {
                    "Alias": Name,
                    "Inspector": {"ID": InspectorID},
                    "Environment": {"ID": EnvironmentID},
                    "Agent": {"ID": AgentID},
                    "Enabled": True,
                    "Visible": True,
                    "FreqType": freq_type,
                    "FreqInterval": interval,
                    "ActiveStart": datetime.now(UTC).strftime("%Y/%m/%d %H:%M:%S"),
                    "Config": Config or {},
                    "SecureConfig": SecureConfig,
                }
            ) | {"Version": None, "ActiveEnd": None}
            return await client.post("v1", "launchpoints", body)

        return await run_tool("liongard_inspections_create_launchpoint", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def liongard_inspections_run(
        launchpointId: Annotated[int, Field(description="Launchpoint id.", ge=1)],
    ) -> str:
        """Run a launchpoint's inspection now. Only when the user explicitly asks."""

        async def action(client: LiongardClient) -> dict:
            job = await client.get("v1", f"launchpoints/{launchpointId}/run")
            return {"done": True, "launchpoint_id": launchpointId, "job": job}

        return await run_tool("liongard_inspections_run", client_factory, action)
