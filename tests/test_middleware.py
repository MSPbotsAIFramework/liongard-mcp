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
"""Credential middleware: 401 / 400 on bad headers, key encoding, instance, isolation."""

import asyncio
import base64

import pytest
from starlette.testclient import TestClient

from liongard_mcp.__main__ import build_http_app
from liongard_mcp.api_client import roar_key
from liongard_mcp.server import GatewayCredentialsMiddleware, _credentials_var, create_mcp_server, get_client_from_context, normalize_instance

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
CREDS = {"X-Liongard-Api-Key": "key-id:secret", "X-Liongard-Instance": "us1"}


def _client() -> TestClient:
    return TestClient(build_http_app(create_mcp_server()))


def test_health_is_local():
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Liongard-Api-Key": "k"}, {"X-Liongard-Instance": "us1"}, CREDS | {"X-Liongard-Api-Key": "${KEY}"}])
def test_missing_headers_return_401(headers):
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | headers)
    assert resp.status_code == 401
    assert resp.json()["required_headers"] == list(CREDS)


def test_invalid_instance_returns_400():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS | {"X-Liongard-Instance": "us1.example.com"})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "value,expected",
    [("us1", "us1"), ("US2", "us2"), ("ca1.app.liongard.com", "ca1"), ("https://us1.app.liongard.com/", "us1"), ("bad_name", None), ("us1.example.com", None)],
)
def test_normalize_instance(value, expected):
    assert normalize_instance(value) == expected


def test_roar_key_encodes_id_and_secret_but_keeps_encoded_keys():
    assert roar_key("key-id:secret") == base64.b64encode(b"key-id:secret").decode()
    encoded = base64.b64encode(b"a:b").decode()
    assert roar_key(f" {encoded} ") == encoded


def test_tools_list_over_http():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS)
    assert resp.status_code == 200
    for name in ("liongard_environments_list", "liongard_metrics_evaluate", "liongard_inventory_devices"):
        assert name in resp.text


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message):
    return None


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, _receive, _send))
    return seen


def test_credentials_reach_request_context_and_are_reset():
    seen = _run_middleware([(b"x-liongard-api-key", b"id:sec"), (b"x-liongard-instance", b"US1.app.liongard.com")])
    client = seen["client"]
    assert client.host == "https://us1.app.liongard.com"
    assert client._headers()["X-ROAR-API-KEY"] == base64.b64encode(b"id:sec").decode()
    assert _credentials_var.get() is None


def test_concurrent_requests_do_not_share_credentials():
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().instance
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().instance))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayCredentialsMiddleware(app)

    def scope(instance: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": [(b"x-liongard-api-key", b"k:s"), (b"x-liongard-instance", instance)]}

    async def both():
        await asyncio.gather(middleware(scope(b"tenant-a"), _receive, _send), middleware(scope(b"tenant-b"), _receive, _send))

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_key():
    seen = _run_middleware([(b"x-liongard-api-key", b"very-secret-key"), (b"x-liongard-instance", b"us1")])
    assert "very-secret-key" not in repr(seen["credentials"])
