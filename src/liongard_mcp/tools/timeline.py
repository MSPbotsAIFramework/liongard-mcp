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
"""Timeline: the history of inspection runs."""

from mcp.server.fastmcp import FastMCP

from ..api_client import LiongardClient
from ._common import READ_ONLY, ClientFactory, Offset, Page, PageSize, locate, pagination, run_tool, v2_page


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_timeline_list(page: Page = None, pageSize: PageSize = None, offset: Offset = None) -> str:
        """List inspection runs, newest first: launchpoint, system, status, start / finish time."""

        async def action(client: LiongardClient) -> dict:
            number, size, start = locate(offset, page, pageSize)
            body = {"Pagination": pagination(number, size), "Sorting": [{"Field": "ID", "Direction": "DESC"}]}
            return v2_page(await client.post("v2", "timelines/query", body), "timeline", number, size, start)

        return await run_tool("liongard_timeline_list", client_factory, action)
