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
"""Asset inventory: identities (user accounts) and device profiles across an environment."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient
from ._common import READ_ONLY, ClientFactory, Filters, Offset, Page, PageSize, RecordId, compact, locate, pagination, run_tool, v2_page

EnvironmentId = Annotated[int, Field(description="Environment id.", ge=1)]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inventory_identities(
        environment: EnvironmentId, page: Page = None, pageSize: PageSize = None, filters: Filters = None, offset: Offset = None
    ) -> str:
        """List an environment's identities (user accounts seen across its systems) with state and sources."""

        async def action(client: LiongardClient) -> dict:
            number, size, start = locate(offset, page, pageSize)
            body = compact({"Environment": environment, "Filters": filters, "Pagination": pagination(number, size)})
            return v2_page(await client.post("v2", "inventory/identities/query", body), "identities", number, size, start)

        return await run_tool("liongard_inventory_identities", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inventory_identity_get(id: RecordId) -> str:
        """Get one identity with the accounts linked to it in each system."""

        async def action(client: LiongardClient) -> Any:
            return await client.get("v2", f"inventory/identities/{id}")

        return await run_tool("liongard_inventory_identity_get", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inventory_devices(
        environment: EnvironmentId, page: Page = None, pageSize: PageSize = None, filters: Filters = None, offset: Offset = None
    ) -> str:
        """List an environment's device profiles (devices seen across its systems) with hostname and state."""

        async def action(client: LiongardClient) -> dict:
            number, size, start = locate(offset, page, pageSize)
            body = compact({"Environment": environment, "Filters": filters, "Pagination": pagination(number, size)})
            return v2_page(await client.post("v2", "inventory/device-profiles/query", body), "devices", number, size, start)

        return await run_tool("liongard_inventory_devices", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_inventory_device_get(id: RecordId) -> str:
        """Get one device profile with the systems that reported it."""

        async def action(client: LiongardClient) -> Any:
            return await client.get("v2", f"inventory/device-profiles/{id}")

        return await run_tool("liongard_inventory_device_get", client_factory, action)
