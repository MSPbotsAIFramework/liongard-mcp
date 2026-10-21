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
"""Environments: the MSP's customers in Liongard."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient
from ._common import READ_ONLY, WRITES, ClientFactory, Page, PageSize, RecordId, compact, enum_value, run_tool, v2_page

EnvironmentTier = Literal["Core", "Essential"]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_environments_list(page: Page = None, pageSize: PageSize = None) -> str:
        """List environments (customers): id, name, short name, tier, parent, systems and agents counts."""

        async def action(client: LiongardClient) -> dict:
            return v2_page(await client.get("v2", "environments", compact({"page": page, "pageSize": pageSize})), "environments")

        return await run_tool("liongard_environments_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_environments_get(id: RecordId) -> str:
        """Get one environment: name, short name, description, tier, parent and group."""

        async def action(client: LiongardClient) -> Any:
            return await client.get("v2", f"environments/{id}")

        return await run_tool("liongard_environments_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def liongard_environments_create(
        Name: Annotated[str, Field(description="Environment (customer) name.", min_length=1)],
        Description: Annotated[str | None, Field(description="Description.")] = None,
        Tier: Annotated[EnvironmentTier | str | None, Field(description="Liongard tier (default Core).")] = None,
        ShortName: Annotated[str | None, Field(description="Short name.")] = None,
        Parent: Annotated[int | None, Field(description="Parent environment id (for child environments).", ge=1)] = None,
        Status: Annotated[str | int | None, Field(description="Accepted for compatibility; the Liongard API ignores it.")] = None,
        Visible: Annotated[bool | None, Field(description="Accepted for compatibility; the Liongard API ignores it.")] = None,
    ) -> str:
        """Create an environment (customer). Only when the user explicitly asks."""
        del Status, Visible  # not part of the Liongard create body (v1 or v2); never sent

        async def action(client: LiongardClient) -> Any:
            body = compact({"Name": Name, "Description": Description, "Tier": enum_value(Tier, EnvironmentTier), "ShortName": ShortName, "Parent": Parent})
            return await client.post("v2", "environments", body)

        return await run_tool("liongard_environments_create", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_environments_count() -> str:
        """Count the environments in the instance."""

        async def action(client: LiongardClient) -> dict:
            return {"count": await client.get("v2", "environments/count")}

        return await run_tool("liongard_environments_count", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_environments_related(id: RecordId) -> str:
        """List what belongs to an environment: launchpoints, systems, agents and integration mappings."""

        async def action(client: LiongardClient) -> Any:
            return await client.get("v2", f"environments/{id}/relatedEntities")

        return await run_tool("liongard_environments_related", client_factory, action)
