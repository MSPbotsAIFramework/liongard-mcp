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
"""tools/list snapshot, annotations and error-envelope mapping. No network access."""

import asyncio
import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from liongard_mcp.api_client import LiongardError
from liongard_mcp.server import INSTRUCTIONS, create_mcp_server
from liongard_mcp.tools.navigation import DOMAINS

P = {"page", "pageSize"}
I = {"id"}

# Tool name -> (parameters the earlier version declared, required parameters).
EXPECTED: dict[str, tuple[set[str], set[str]]] = {
    "liongard_navigate": ({"domain"}, {"domain"}),
    "liongard_agents_list": (P, set()),
    "liongard_agents_delete": (I, I),
    "liongard_detections_list": (P | {"startDate", "endDate", "filters"}, set()),
    "liongard_detections_get": (I, I),
    "liongard_environments_list": (P, set()),
    "liongard_environments_get": (I, I),
    "liongard_environments_create": ({"Name", "Description", "Tier"}, {"Name"}),
    "liongard_environments_count": (set(), set()),
    "liongard_environments_related": (I, I),
    "liongard_inspections_inspectors": (P, set()),
    "liongard_inspections_launchpoints": (P, set()),
    "liongard_inspections_create_launchpoint": ({"Name", "InspectorID", "EnvironmentID", "AgentID", "Schedule"}, {"Name", "InspectorID", "EnvironmentID"}),
    "liongard_inspections_run": ({"launchpointId"}, {"launchpointId"}),
    "liongard_inventory_identities": ({"environment", "filters"} | P, {"environment"}),
    "liongard_inventory_identity_get": (I, I),
    "liongard_inventory_devices": ({"environment", "filters"} | P, {"environment"}),
    "liongard_inventory_device_get": (I, I),
    "liongard_metrics_list": (set(), set()),
    "liongard_metrics_evaluate": ({"MetricIDs", "EnvironmentIDs"} | P, set()),
    "liongard_metrics_evaluate_systems": ({"MetricIDs", "EnvironmentIDs"} | P, set()),
    "liongard_systems_list": (P, set()),
    "liongard_systems_get": (I, I),
    "liongard_timeline_list": (P, set()),
}
WRITE_TOOLS = {"liongard_environments_create", "liongard_inspections_create_launchpoint", "liongard_inspections_run", "liongard_agents_delete"}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_params(tools, name):
    params, required = EXPECTED[name]
    schema = tools[name].inputSchema
    assert params <= set(schema["properties"])
    assert set(schema.get("required", [])) == required


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is (name not in WRITE_TOOLS)
    assert bool(annotations.destructiveHint) is (name == "liongard_agents_delete")
    assert (annotations.openWorldHint is False) is (name == "liongard_navigate")


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly ask" in tools[name].description


def test_delete_takes_confirm(tools):
    assert "confirm" in tools["liongard_agents_delete"].inputSchema["properties"]


def test_navigate_lists_every_tool():
    listed = {tool for _, names in DOMAINS.values() for tool in names}
    assert listed | {"liongard_navigate"} == set(EXPECTED)


def test_page_size_is_capped_at_200(tools):
    paged = [t for t in tools.values() if "pageSize" in t.inputSchema["properties"]]
    assert len(paged) == 11
    for tool in paged:
        assert tool.inputSchema["properties"]["pageSize"]["anyOf"][0]["maximum"] == 200, tool.name
    with pytest.raises(ToolError, match="less than or equal to 200"):
        asyncio.run(create_mcp_server().call_tool("liongard_metrics_evaluate", {"pageSize": 201}))


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500
    assert "\n" in INSTRUCTIONS


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (400, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(LiongardError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("liongard_environments_list", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
