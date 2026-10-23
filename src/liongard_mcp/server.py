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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import LiongardClient, LiongardCredentials, roar_key
from .config import Settings

HEADER_API_KEY = "X-Liongard-Api-Key"
HEADER_INSTANCE = "X-Liongard-Instance"
REQUIRED_HEADERS = [HEADER_API_KEY, HEADER_INSTANCE]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")
_INSTANCE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[LiongardCredentials | None] = contextvars.ContextVar("liongard_credentials", default=None)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("liongard_request_id", default="-")

INSTRUCTIONS = (
    "Liongard inspects the systems MSPs manage: environments are customers; "
    "inspectors are integration types (Microsoft 365, firewalls, AD ...); a "
    "launchpoint is an inspector configured for one environment, producing a "
    "system that is inspected on a schedule. Detections record changes found "
    "between inspections; metrics are named values computed from system data.\n"
    "Usage:\n"
    "- liongard_environments_list -> liongard_systems_list / "
    "liongard_inspections_launchpoints (by environment).\n"
    "- What changed: liongard_detections_list (startDate, endDate).\n"
    "- Values such as licence counts: liongard_metrics_list -> "
    "liongard_metrics_evaluate(MetricIDs, EnvironmentIDs).\n"
    "- Users / devices: liongard_inventory_identities / _devices(environment).\n"
    "Creating environments or launchpoints and running inspections only when "
    "the user explicitly asks; deleting an agent also needs confirm: true."
)


def get_client_from_context() -> LiongardClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return LiongardClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def normalize_instance(value: str) -> str | None:
    """'us1', 'US1', 'us1.app.liongard.com' or 'https://us1.app.liongard.com/' -> 'us1'; None when invalid."""
    text = re.sub(r"^https?://", "", value.strip().lower()).split("/", 1)[0]
    text = text.removesuffix(".app.liongard.com")
    return text if _INSTANCE.match(text) else None


def _error(scope: Scope, receive: Receive, send: Send, status: int, error: str, message: str):
    return JSONResponse({"error": error, "message": message, "required_headers": REQUIRED_HEADERS}, status_code=status)(
        scope, receive, send
    )


class GatewayCredentialsMiddleware:
    """Reads the Liongard key and instance on /mcp requests into the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        api_key = _clean(request.headers.get(HEADER_API_KEY))
        instance_raw = _clean(request.headers.get(HEADER_INSTANCE))
        if not (api_key and instance_raw):
            missing = [h for h, v in ((HEADER_API_KEY, api_key), (HEADER_INSTANCE, instance_raw)) if not v]
            await _error(scope, receive, send, 401, "Missing credentials", f"Missing header(s): {', '.join(missing)}")
            return
        instance = normalize_instance(instance_raw)
        if instance is None:
            await _error(scope, receive, send, 400, "Invalid credentials", f"{HEADER_INSTANCE} must be the instance name, e.g. us1")
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(LiongardCredentials(instance, roar_key(api_key)))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="liongard-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], LiongardClient | None] = get_client_from_context

    from .tools import agents, detections, environments, inspections, inventory, metrics, navigation, systems, timeline

    for module in (navigation, environments, agents, inspections, systems, detections, metrics, inventory, timeline):
        module.register(mcp, client_factory)

    return mcp
