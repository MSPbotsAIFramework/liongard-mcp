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
"""Detections: changes Liongard found between inspections."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient
from ._common import READ_ONLY, ClientFactory, Filters, Offset, Page, PageSize, RecordId, compact, locate, pagination, run_tool, v2_page


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_detections_list(
        page: Page = None,
        pageSize: PageSize = None,
        startDate: Annotated[str | None, Field(description="ISO 8601: detections on or after.")] = None,
        endDate: Annotated[str | None, Field(description="ISO 8601: detections on or before.")] = None,
        filters: Filters = None,
        offset: Offset = None,
    ) -> str:
        """List detections (changes found by inspections): system, environment, what changed and when."""

        async def action(client: LiongardClient) -> dict:
            number, size, start = locate(offset, page, pageSize)
            body = compact({"Pagination": pagination(number, size), "StartDate": startDate, "EndDate": endDate, "Filters": filters})
            return v2_page(await client.post("v2", "detections", body), "detections", number, size, start)

        return await run_tool("liongard_detections_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_detections_get(id: RecordId) -> str:
        """Get one detection with the change details."""

        async def action(client: LiongardClient) -> Any:
            return await client.get("v1", f"detections/{id}")

        return await run_tool("liongard_detections_get", client_factory, action)
