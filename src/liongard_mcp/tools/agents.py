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
"""Agents: the Liongard agents that run inspections."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import LiongardClient
from ._common import DESTRUCTIVE, READ_ONLY, ClientFactory, Confirm, Offset, Page, PageSize, RecordId, locate, not_confirmed_result, pagination, run_tool, v2_page


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_agents_list(page: Page = None, pageSize: PageSize = None, offset: Offset = None) -> str:
        """List agents: id, name, type (cloud / on-premises), environment, status, version, last check-in."""

        async def action(client: LiongardClient) -> dict:
            number, size, start = locate(offset, page, pageSize)
            return v2_page(await client.post("v2", "view/agents", {"Pagination": pagination(number, size)}), "agents", number, size, start)

        return await run_tool("liongard_agents_list", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def liongard_agents_delete(id: RecordId, confirm: Confirm = None) -> str:
        """Delete an agent; inspections that run on it stop. Needs confirm: true.

        Only when the user explicitly asks for that agent.
        """

        async def action(client: LiongardClient) -> Any:
            if confirm is not True:
                return not_confirmed_result(f"Delete Liongard agent {id} (its launchpoints stop running)")
            await client.delete("v1", f"agents/{id}")
            return {"done": True, "deleted_agent_id": id}

        return await run_tool("liongard_agents_delete", client_factory, action)
