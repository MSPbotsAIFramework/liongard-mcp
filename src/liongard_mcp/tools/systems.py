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
"""Systems: what a launchpoint inspects (a tenant, a firewall, a domain ...)."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient, LiongardError
from ._common import READ_ONLY, ClientFactory, Offset, Page, PageSize, RecordId, condition, local_page, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_systems_list(page: Page = None, pageSize: PageSize = None, offset: Offset = None) -> str:
        """List systems: id, name, launchpoint, environment, status and last inspection time."""

        async def action(client: LiongardClient) -> dict:
            return local_page(await client.get("v1", "systems"), "systems", page, pageSize, offset)

        return await run_tool("liongard_systems_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_systems_get(
        id: RecordId,
        include_data: Annotated[bool, Field(description="Also return the raw data of the latest inspection (can be large).")] = False,
    ) -> str:
        """Get one system; optionally with the raw data of its latest inspection."""

        async def action(client: LiongardClient) -> Any:
            rows = await client.get("v1", "systems", [("conditions[]", condition("ID", "=", id))])
            rows = rows if isinstance(rows, list) else []
            system = next((r for r in rows if isinstance(r, dict) and str(r.get("ID")) == str(id)), rows[0] if rows else None)
            if system is None:
                raise LiongardError(404, f"No Liongard system {id}.")
            if include_data:
                return {"system": system, "data": await client.post("v1", f"systems/{id}/view")}
            return system

        return await run_tool("liongard_systems_get", client_factory, action)
