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
"""Metrics: named values computed from system data (licence counts, MFA status ...)."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import LiongardClient
from ._common import READ_ONLY, ClientFactory, Page, PageSize, compact, pagination, run_tool, v2_page

MetricIds = Annotated[list[int] | None, Field(description="Metric ids (liongard_metrics_list).")]
EnvironmentIds = Annotated[list[int] | None, Field(description="Only these environment ids.")]


def _environment_filter(ids: list[int] | None) -> list[dict] | None:
    return [{"Field": "EnvironmentID", "Op": "equal_to", "Values": ids}] if ids else None


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def liongard_metrics_list() -> str:
        """List metrics: id, name, inspector, query and whether it is displayed."""

        async def action(client: LiongardClient) -> dict:
            return v2_page(await client.get("v2", "metrics", {"Page": 1, "PageSize": 2000}), "metrics")

        return await run_tool("liongard_metrics_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_metrics_evaluate(
        MetricIDs: MetricIds = None,
        EnvironmentIDs: EnvironmentIds = None,
        page: Page = None,
        pageSize: PageSize = None,
    ) -> str:
        """Evaluate metrics across systems: the value of each metric per system and environment."""

        async def action(client: LiongardClient) -> dict:
            if not MetricIDs:
                raise ValueError("Pass MetricIDs: Liongard evaluates the metrics you name (see liongard_metrics_list).")
            body = compact({"Metrics": MetricIDs, "Filters": _environment_filter(EnvironmentIDs), "Pagination": pagination(page, pageSize)})
            return v2_page(await client.post("v2", "metrics/evaluate", body), "values")

        return await run_tool("liongard_metrics_evaluate", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def liongard_metrics_evaluate_systems(
        MetricIDs: MetricIds = None,
        EnvironmentIDs: EnvironmentIds = None,
        page: Page = None,
        pageSize: PageSize = None,
        SystemIDs: Annotated[list[int] | None, Field(description="Systems to evaluate all displayed metrics for; required by Liongard.")] = None,
    ) -> str:
        """Evaluate every displayed metric for given systems; optionally keep only some metric ids."""

        async def action(client: LiongardClient) -> Any:
            if not SystemIDs:
                raise ValueError("Pass SystemIDs: this evaluates the metrics of specific systems (see liongard_systems_list).")
            body = compact({"Systems": SystemIDs, "Filters": _environment_filter(EnvironmentIDs), "Pagination": pagination(page, pageSize)})
            result = v2_page(await client.post("v2", "metrics/evaluate/systems", body), "values")
            if MetricIDs:
                wanted = {str(m) for m in MetricIDs}
                kept = [r for r in result["values"] if not isinstance(r, dict) or str(r.get("MetricID", r.get("ID"))) in wanted]
                result |= {"values": kept, "count": len(kept)}
            return result

        return await run_tool("liongard_metrics_evaluate_systems", client_factory, action)
