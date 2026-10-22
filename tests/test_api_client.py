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
"""Request shapes, paging, retries and tool behaviour against a mocked Liongard API."""

import json

import httpx
import pytest

from liongard_mcp import api_client
from liongard_mcp.api_client import LiongardClient, LiongardCredentials, LiongardError
from liongard_mcp.server import _credentials_var, create_mcp_server
from liongard_mcp.tools.inspections import schedule

CREDS = LiongardCredentials("us1", "ZW5jb2RlZA==")


def paged(rows, total=None, more=False):
    return {"Data": rows, "Pagination": {"TotalRows": total if total is not None else len(rows), "HasMoreRows": more, "CurrentPage": 1, "TotalPages": 1, "PageSize": 50}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by method + version/path (trailing slash removed)."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/").rstrip("/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.rstrip("/") == f"/api/{path}" and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder), follow_redirects=True)
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> LiongardClient:
    return LiongardClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder), follow_redirects=True))


# ---- client ----------------------------------------------------------------


async def test_key_header_host_and_trailing_slash():
    rec = Recorder()
    await _client(rec).get("v1", "environments/count")
    request = rec.requests[0]
    assert request.headers["x-roar-api-key"] == "ZW5jb2RlZA=="
    assert str(request.url) == "https://us1.app.liongard.com/api/v1/environments/count/"


async def test_redirect_is_followed_with_the_key():
    def first(request):
        if "hop" not in str(request.url):
            return httpx.Response(301, headers={"Location": "https://us1.app.liongard.com/api/v2/environments/count/?hop=1"})
        return httpx.Response(200, json=7)

    rec = Recorder({"v2/environments/count": first})
    assert await _client(rec).get("v2", "environments/count") == 7
    assert rec.requests[1].headers["x-roar-api-key"] == "ZW5jb2RlZA=="


async def test_get_retries_5xx_but_writes_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json=[])])
    rec = Recorder({"GET v1/inspectors": lambda r: next(replies), "POST v2/environments": lambda r: httpx.Response(500)})
    client = _client(rec)
    await client.get("v1", "inspectors")
    with pytest.raises(LiongardError):
        await client.post("v2", "environments", {})
    assert len(rec.calls("v1/inspectors")) == 2 and len(rec.calls("v2/environments", "POST")) == 1


async def test_error_message(monkeypatch):
    rec = Recorder({"v2/environments/9": lambda r: httpx.Response(401, json={"message": "Invalid API key"})})
    result = await _call(monkeypatch, rec, "liongard_environments_get", {"id": 9})
    assert result["error"]["code"] == "unauthorized" and result["error"]["message"].endswith("Invalid API key")


# ---- environments / agents ----------------------------------------------------


async def test_environments_list_and_count(monkeypatch):
    rec = Recorder({"v2/environments": paged([{"ID": 1, "Name": "Example Co"}], total=120, more=True), "v2/environments/count": 120})
    listed = await _call(monkeypatch, rec, "liongard_environments_list", {"page": 2, "pageSize": 25})
    params = rec.calls("v2/environments")[0].url.params
    assert (params["page"], params["pageSize"]) == ("2", "25")
    assert listed == {"environments": [{"ID": 1, "Name": "Example Co"}], "count": 1, "total": 120, "page": 1, "has_more": True, "offset": 25, "next_offset": 26}
    assert (await _call(monkeypatch, rec, "liongard_environments_count", {})) == {"count": 120}


async def test_environment_create_and_related(monkeypatch):
    rec = Recorder({"POST v2/environments": {"ID": 5}, "v2/environments/5/relatedEntities": {"Launchpoints": [1]}})
    await _call(monkeypatch, rec, "liongard_environments_create", {"Name": "Example Co", "Tier": "Essential", "Status": "Active"})
    assert body(rec.calls("v2/environments", "POST")[0]) == {"Name": "Example Co", "Tier": "Essential"}
    assert (await _call(monkeypatch, rec, "liongard_environments_related", {"id": 5})) == {"Launchpoints": [1]}


async def test_environment_create_accepts_and_ignores_status_and_visible(monkeypatch):
    rec = Recorder({"POST v2/environments": {"ID": 6}})
    result = await _call(monkeypatch, rec, "liongard_environments_create", {"Name": "Example Co", "Status": 1, "Visible": False})
    assert result == {"ID": 6}
    assert body(rec.calls("v2/environments", "POST")[0]) == {"Name": "Example Co"}


async def test_agents_list_and_delete(monkeypatch):
    rec = Recorder({"POST v2/view/agents": paged([{"ID": 3}]), "DELETE v1/agents/3": lambda r: httpx.Response(204)})
    listed = await _call(monkeypatch, rec, "liongard_agents_list", {"pageSize": 10})
    assert body(rec.calls("v2/view/agents")[0]) == {"Pagination": {"Page": 1, "PageSize": 10}} and listed["agents"] == [{"ID": 3}]
    preview = await _call(monkeypatch, rec, "liongard_agents_delete", {"id": 3})
    assert preview["done"] is False and not rec.calls("v1/agents/3")
    await _call(monkeypatch, rec, "liongard_agents_delete", {"id": 3, "confirm": True})
    assert rec.calls("v1/agents/3", "DELETE")


# ---- inspections --------------------------------------------------------------


async def test_v1_lists_are_paged_locally(monkeypatch):
    rec = Recorder({"v1/launchpoints": [{"ID": i} for i in range(120)]})
    result = await _call(monkeypatch, rec, "liongard_inspections_launchpoints", {"page": 3, "pageSize": 50})
    assert [r["ID"] for r in result["launchpoints"]] == list(range(100, 120))
    assert (result["total"], result["has_more"]) == (120, False)


@pytest.mark.parametrize(
    "value,expected",
    [(None, ("day", 1)), ("daily", ("day", 1)), ("hourly", ("hour", 1)), ("every 6 hours", ("hour", 6)), ("12h", ("hour", 12)), ("2 days", ("day", 2))],
)
def test_schedule(value, expected):
    assert schedule(value) == expected


async def test_create_launchpoint_body(monkeypatch):
    rec = Recorder({"POST v1/launchpoints": {"ID": 77}})
    args = {"Name": "M365 - Example Co", "InspectorID": 13, "EnvironmentID": 1000, "AgentID": 1106, "Schedule": "every 6 hours", "Config": {"TenantId": "x"}}
    result = await _call(monkeypatch, rec, "liongard_inspections_create_launchpoint", args)
    sent = body(rec.requests[0])
    assert sent["Alias"] == "M365 - Example Co" and sent["Inspector"] == {"ID": 13} and sent["Environment"] == {"ID": 1000} and sent["Agent"] == {"ID": 1106}
    assert (sent["FreqType"], sent["FreqInterval"], sent["Enabled"], sent["Config"]) == ("hour", 6, True, {"TenantId": "x"})
    assert sent["Version"] is None and sent["ActiveEnd"] is None and len(sent["ActiveStart"]) == 19
    assert result == {"ID": 77}


async def test_create_launchpoint_needs_agent_and_valid_schedule(monkeypatch):
    rec = Recorder()
    no_agent = await _call(monkeypatch, rec, "liongard_inspections_create_launchpoint", {"Name": "x", "InspectorID": 1, "EnvironmentID": 2})
    assert "AgentID" in no_agent["error"]["message"]
    bad = await _call(monkeypatch, rec, "liongard_inspections_create_launchpoint", {"Name": "x", "InspectorID": 1, "EnvironmentID": 2, "AgentID": 3, "Schedule": "sometimes"})
    assert bad["error"]["code"] == "invalid_argument" and rec.requests == []


async def test_run_launchpoint_uses_get(monkeypatch):
    rec = Recorder({"v1/launchpoints/77/run": 14822})
    result = await _call(monkeypatch, rec, "liongard_inspections_run", {"launchpointId": 77})
    assert rec.requests[0].method == "GET" and result == {"done": True, "launchpoint_id": 77, "job": 14822}


# ---- systems / detections / timeline -------------------------------------------


async def test_system_get_by_condition_and_data(monkeypatch):
    rec = Recorder({"v1/systems": [{"ID": 42, "Name": "example.onmicrosoft.com"}], "POST v1/systems/42/view": {"Users": []}})
    system = await _call(monkeypatch, rec, "liongard_systems_get", {"id": 42})
    assert json.loads(rec.requests[0].url.params["conditions[]"]) == {"path": "ID", "op": "=", "value": 42}
    assert system == {"ID": 42, "Name": "example.onmicrosoft.com"}
    full = await _call(monkeypatch, rec, "liongard_systems_get", {"id": 42, "include_data": True})
    assert full["data"] == {"Users": []}


async def test_missing_system_is_not_found(monkeypatch):
    result = await _call(monkeypatch, Recorder({"v1/systems": []}), "liongard_systems_get", {"id": 42})
    assert result["error"]["code"] == "not_found"


async def test_detections_list_body(monkeypatch):
    rec = Recorder({"POST v2/detections": paged([{"ID": 1}])})
    args = {"startDate": "2026-10-01T00:00:00Z", "filters": [{"FilterBy": "EnvironmentID", "Op": "equal_to", "Values": [5]}]}
    result = await _call(monkeypatch, rec, "liongard_detections_list", args)
    assert body(rec.requests[0]) == {
        "Pagination": {"Page": 1, "PageSize": 50},
        "StartDate": "2026-10-01T00:00:00Z",
        "Filters": [{"FilterBy": "EnvironmentID", "Op": "equal_to", "Values": [5]}],
    }
    assert result["detections"] == [{"ID": 1}]
    await _call(monkeypatch, Recorder({"v1/detections/1": {"ID": 1}}), "liongard_detections_get", {"id": 1})


async def test_timeline_newest_first(monkeypatch):
    rec = Recorder({"POST v2/timelines/query": paged([{"ID": 9}])})
    await _call(monkeypatch, rec, "liongard_timeline_list", {})
    assert body(rec.requests[0])["Sorting"] == [{"Field": "ID", "Direction": "DESC"}]


# ---- metrics / inventory --------------------------------------------------------


async def test_metrics_evaluate_body(monkeypatch):
    rec = Recorder({"POST v2/metrics/evaluate": paged([{"MetricID": 3, "Value": 12}])})
    result = await _call(monkeypatch, rec, "liongard_metrics_evaluate", {"MetricIDs": [3], "EnvironmentIDs": [5, 6], "pageSize": 100})
    assert body(rec.requests[0]) == {
        "Metrics": [3],
        "Filters": [{"Field": "EnvironmentID", "Op": "equal_to", "Values": [5, 6]}],
        "Pagination": {"Page": 1, "PageSize": 100},
    }
    assert result["values"] == [{"MetricID": 3, "Value": 12}]


async def test_metrics_evaluate_requires_metrics(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "liongard_metrics_evaluate", {})
    assert result["error"]["code"] == "invalid_argument" and rec.requests == []


async def test_metrics_evaluate_systems(monkeypatch):
    rows = [{"MetricID": 3, "Value": 1}, {"MetricID": 4, "Value": 2}]
    rec = Recorder({"POST v2/metrics/evaluate/systems": paged(rows)})
    result = await _call(monkeypatch, rec, "liongard_metrics_evaluate_systems", {"SystemIDs": [42], "MetricIDs": [4]})
    assert body(rec.requests[0])["Systems"] == [42]
    assert result["values"] == [{"MetricID": 4, "Value": 2}] and result["count"] == 1
    missing = await _call(monkeypatch, Recorder(), "liongard_metrics_evaluate_systems", {"MetricIDs": [4]})
    assert "SystemIDs" in missing["error"]["message"]


async def test_metrics_list(monkeypatch):
    rec = Recorder({"v2/metrics": paged([{"ID": 3}])})
    await _call(monkeypatch, rec, "liongard_metrics_list", {})
    assert rec.requests[0].url.params["PageSize"] == "2000"


@pytest.mark.parametrize("tool,path", [("liongard_inventory_identities", "identities"), ("liongard_inventory_devices", "device-profiles")])
async def test_inventory_queries(monkeypatch, tool, path):
    rec = Recorder({f"POST v2/inventory/{path}/query": paged([{"ID": 1}])})
    await _call(monkeypatch, rec, tool, {"environment": 4, "filters": [{"FilterBy": "InventoryState", "Op": "matches_exactly", "Value": "Inventory"}]})
    sent = body(rec.requests[0])
    assert sent["Environment"] == 4 and sent["Filters"][0]["FilterBy"] == "InventoryState" and sent["Pagination"] == {"Page": 1, "PageSize": 50}


@pytest.mark.parametrize("tool,path", [("liongard_inventory_identity_get", "v2/inventory/identities/8"), ("liongard_inventory_device_get", "v2/inventory/device-profiles/8")])
async def test_inventory_gets(monkeypatch, tool, path):
    rec = Recorder({path: {"ID": 8}})
    assert await _call(monkeypatch, rec, tool, {"id": 8}) == {"ID": 8}


@pytest.mark.parametrize("given,sent", [("core", "Core"), ("ESSENTIAL", "Essential"), ("Premium", "Premium")])
async def test_environment_create_tier_normalized_or_passed_through(monkeypatch, given, sent):
    rec = Recorder({"POST v2/environments": {"ID": 7}})
    await _call(monkeypatch, rec, "liongard_environments_create", {"Name": "Example Co", "Tier": given})
    assert body(rec.calls("v2/environments", "POST")[0])["Tier"] == sent


# ---- Page-number paging that survives truncation (offset / next_offset) -----------------------------
# Self-test checklist: a cut page continues right after the last record returned (from page 1 and
# from a later page); offset aligned / not aligned to a page; offset past the end; offset wins over
# page; page-only calls send the same request as before; no retry hint for a page size.

TOTAL = 137
ROWS = [{"ID": i, "Name": f"Row {i}", **{f"f{k}": f"value {k}" for k in range(40)}} for i in range(TOTAL)]
SMALL = [{"ID": i} for i in range(TOTAL)]

# (tool, route, list key, extra arguments, how Liongard pages it)
PAGED_TOOLS = [
    ("liongard_environments_list", "GET v2/environments", "environments", {}, "query"),
    ("liongard_agents_list", "POST v2/view/agents", "agents", {}, "body"),
    ("liongard_detections_list", "POST v2/detections", "detections", {}, "body"),
    ("liongard_timeline_list", "POST v2/timelines/query", "timeline", {}, "body"),
    ("liongard_metrics_evaluate", "POST v2/metrics/evaluate", "values", {"MetricIDs": [1]}, "body"),
    ("liongard_metrics_evaluate_systems", "POST v2/metrics/evaluate/systems", "values", {"SystemIDs": [1]}, "body"),
    ("liongard_inventory_identities", "POST v2/inventory/identities/query", "identities", {"environment": 4}, "body"),
    ("liongard_inventory_devices", "POST v2/inventory/device-profiles/query", "devices", {"environment": 4}, "body"),
    ("liongard_inspections_inspectors", "GET v1/inspectors", "inspectors", {}, "whole"),
    ("liongard_inspections_launchpoints", "GET v1/launchpoints", "launchpoints", {}, "whole"),
    ("liongard_systems_list", "GET v1/systems", "systems", {}, "whole"),
]
IDS = [t[0] for t in PAGED_TOOLS]


def _sent(request, mode):
    """(page, page size) a request asked for; None where it did not say."""
    if mode == "body":
        paging = body(request)["Pagination"]
        return paging["Page"], paging["PageSize"]
    params = request.url.params
    return (int(params["page"]) if "page" in params else None, int(params["pageSize"]) if "pageSize" in params else None)


def _api(route, rows, mode, default_size=50):
    """Pages by page number + page size like Liongard v2; v1 lists come back whole."""

    def reply(request):
        if mode == "whole":
            return httpx.Response(200, json=rows)
        number, size = _sent(request, mode)
        number, size = number or 1, size or default_size
        chunk = rows[(number - 1) * size : number * size]
        more = number * size < len(rows)
        paging = {"TotalRows": len(rows), "HasMoreRows": more, "CurrentPage": number, "TotalPages": (len(rows) + size - 1) // size, "PageSize": size}
        return httpx.Response(200, json={"Data": chunk, "Pagination": paging})

    return Recorder({route: reply})


async def _walk(monkeypatch, rec, tool, key, args):
    ids, calls, cut = [], 0, 0
    while True:
        result = await _call(monkeypatch, rec, tool, args)
        calls += 1
        assert "retry_page_size" not in result, result.get("note")
        cut += bool(result.get("truncated"))
        ids += [r["ID"] for r in result.get(key, [])]
        if result.get("next_offset") is None:
            return ids, cut
        args = {k: v for k, v in args.items() if k != "page"} | {"offset": result["next_offset"]}
        assert calls < 200


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
async def test_cut_pages_continue_without_gaps_from_page_1(monkeypatch, tool, route, key, extra, mode):
    ids, cut = await _walk(monkeypatch, _api(route, ROWS, mode), tool, key, extra | {"pageSize": 50})
    assert cut > 0  # pages really were cut
    assert ids == [r["ID"] for r in ROWS]  # no gaps, no duplicates


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
async def test_cut_pages_continue_without_gaps_from_a_later_page(monkeypatch, tool, route, key, extra, mode):
    ids, cut = await _walk(monkeypatch, _api(route, ROWS, mode), tool, key, extra | {"page": 3, "pageSize": 40})
    assert cut > 0
    assert ids == [r["ID"] for r in ROWS[80:]]


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
@pytest.mark.parametrize("offset,size,page,first", [(30, 25, 2, 30), (50, 25, 3, 50), (0, 25, 1, 0)])
async def test_offset_reads_the_page_that_holds_it(monkeypatch, tool, route, key, extra, mode, offset, size, page, first):
    rec = _api(route, SMALL, mode)
    result = await _call(monkeypatch, rec, tool, extra | {"offset": offset, "pageSize": size})
    if mode != "whole":
        assert _sent(rec.requests[0], mode) == (page, size)
    assert result[key][0]["ID"] == first and result["offset"] == offset and result["page"] == page
    assert result["next_offset"] == page * size  # rest of the page returned, next page starts after it


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
async def test_offset_past_the_end_is_empty(monkeypatch, tool, route, key, extra, mode):
    result = await _call(monkeypatch, _api(route, SMALL, mode), tool, extra | {"offset": 500, "pageSize": 25})
    assert (result.get(key, []), result["count"], result["has_more"], result.get("next_offset")) == ([], 0, False, None)


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
async def test_offset_wins_over_page(monkeypatch, tool, route, key, extra, mode):
    rec = _api(route, SMALL, mode)
    result = await _call(monkeypatch, rec, tool, extra | {"offset": 10, "page": 4, "pageSize": 10})
    if mode != "whole":
        assert _sent(rec.requests[0], mode) == (2, 10)
    assert result[key][0]["ID"] == 10 and result["offset"] == 10


@pytest.mark.parametrize("tool,route,key,extra,mode", PAGED_TOOLS, ids=IDS)
async def test_page_only_sends_the_same_request_as_before(monkeypatch, tool, route, key, extra, mode):
    rec = _api(route, SMALL, mode)
    result = await _call(monkeypatch, rec, tool, extra | {"page": 2, "pageSize": 25})
    if mode == "body":
        assert body(rec.requests[0])["Pagination"] == {"Page": 2, "PageSize": 25}
    elif mode == "query":
        assert dict(rec.requests[0].url.params) == {"page": "2", "pageSize": "25"}
    else:
        assert not rec.requests[0].url.params
    assert [r["ID"] for r in result[key]] == list(range(25, 50))
    assert (result["page"], result["offset"], result["next_offset"], result["has_more"]) == (2, 25, 50, True)


async def test_environments_page_without_size_sends_only_page_and_counts_the_reported_size(monkeypatch):
    rec = _api("GET v2/environments", SMALL, "query", default_size=20)
    result = await _call(monkeypatch, rec, "liongard_environments_list", {"page": 2})
    assert dict(rec.requests[0].url.params) == {"page": "2"}
    assert [r["ID"] for r in result["environments"]] == list(range(20, 40))
    assert (result["offset"], result["next_offset"]) == (20, 40)
    bare = _api("GET v2/environments", SMALL, "query", default_size=20)
    await _call(monkeypatch, bare, "liongard_environments_list", {})
    assert not bare.requests[0].url.params


async def test_metrics_evaluate_systems_filter_keeps_record_positions(monkeypatch):
    rows = [{"ID": i, "MetricID": 4 if i % 2 else 3} for i in range(60)]
    rec = _api("POST v2/metrics/evaluate/systems", rows, "body")
    result = await _call(monkeypatch, rec, "liongard_metrics_evaluate_systems", {"SystemIDs": [1], "MetricIDs": [4], "pageSize": 25})
    assert [r["ID"] for r in result["values"]] == list(range(1, 25, 2))
    assert result["next_offset"] == 25  # counts Liongard records, not the kept ones
    big = [r | {f"f{k}": f"value {k}" for k in range(80)} for r in rows]
    rec = _api("POST v2/metrics/evaluate/systems", big, "body")
    cut = await _call(monkeypatch, rec, "liongard_metrics_evaluate_systems", {"SystemIDs": [1], "MetricIDs": [4], "pageSize": 50})
    assert cut["truncated"] is True and "next_offset" not in cut  # a cut filtered list maps to no exact position
