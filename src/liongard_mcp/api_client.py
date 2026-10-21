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
"""Async client for the Liongard API (v1 and v2) of one instance."""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any, Literal

import httpx

from ._json import error_envelope

logger = logging.getLogger("liongard_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 20.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0
_USER_AGENT = "MSPbots-Liongard-MCP/1.0"

Version = Literal["v1", "v2"]

# One connection pool for the process. It never holds credentials: the
# X-ROAR-API-KEY header is set per request from the caller's own key. Liongard
# answers every call with a 301 to its API host first, so redirects are followed
# (httpx keeps headers on same-origin redirects and drops them otherwise).
_shared_http_client: httpx.AsyncClient | None = None


class _RejectAllCookies(DefaultCookiePolicy):
    """Never store or send a cookie: the HTTP client is shared by every tenant."""

    def set_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False

    def return_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False


def _no_cookies() -> CookieJar:
    # A plain CookieJar: httpx uses it as is (an httpx.Cookies would be copied into a default jar).
    return CookieJar(policy=_RejectAllCookies())


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(cookies=_no_cookies(), timeout=_TIMEOUT, follow_redirects=True)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    409: ("invalid_argument", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class LiongardError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Liongard API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


def roar_key(value: str) -> str:
    """The X-ROAR-API-KEY value: base64 of 'access-key-id:secret'; an already encoded key is used as is."""
    text = value.strip()
    if ":" in text:
        return base64.b64encode(text.encode()).decode()
    return text


@dataclass(frozen=True)
class LiongardCredentials:
    instance: str  # e.g. us1
    api_key: str  # base64(access key id:secret)

    def __repr__(self) -> str:  # never leak the key into logs or tracebacks
        return f"LiongardCredentials(instance={self.instance!r}, api_key=<redacted>)"


class LiongardClient:
    """Thin wrapper over one Liongard instance's API for one caller's key."""

    def __init__(self, credentials: LiongardCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client
        self.instance = credentials.instance
        self.host = f"https://{credentials.instance}.app.liongard.com"

    def _headers(self) -> dict[str, str]:
        return {"X-ROAR-API-KEY": self._credentials.api_key, "Accept": "application/json", "User-Agent": _USER_AGENT}

    def url(self, version: Version, path: str) -> str:
        # Trailing slash avoids an extra redirect hop.
        clean = path.strip("/")
        return f"{self.host}/api/{version}/{clean}/"

    async def get(self, version: Version, path: str, params: Any = None) -> Any:
        return await self.request("GET", version, path, params=params)

    async def post(self, version: Version, path: str, body: Any = None, params: Any = None) -> Any:
        return await self.request("POST", version, path, params=params, body=body)

    async def delete(self, version: Version, path: str) -> Any:
        return await self.request("DELETE", version, path)

    async def request(self, method: str, version: Version, path: str, params: Any = None, body: Any = None) -> Any:
        http = self._http or _get_shared_http_client()
        url = self.url(version, path)
        if isinstance(params, dict):
            params = {k: (("true" if v else "false") if isinstance(v, bool) else v) for k, v in params.items() if v is not None}
        headers = self._headers()
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: LiongardError | None = None
            try:
                kwargs: dict[str, Any] = {"params": params, "headers": headers}
                if body is not None:
                    kwargs["json"] = body
                resp = await http.request(method, url, **kwargs)
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, LiongardError(0, f"Timed out calling Liongard ({method} {version}/{path})")
            except httpx.RequestError as e:
                status, error = 0, LiongardError(0, f"Network error calling Liongard ({method} {version}/{path}): {type(e).__name__}")

            logger.info("liongard_api method=%s path=%s/%s status=%s ms=%d attempt=%d", method, version, path, status, (time.monotonic() - t0) * 1000, attempt)

            # 429 is refused before processing, so any method may retry it; other
            # failures are retried only for reads, so a write never runs twice.
            retryable = status == 429 or (method == "GET" and (status == 0 or status >= 500))
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                raise error
            assert resp is not None
            if resp.status_code >= 400:
                raise LiongardError(resp.status_code, _error_message(resp, f"{version}/{path}"))
            if not resp.content or not resp.content.strip():
                return None
            try:
                return resp.json()
            except ValueError:
                return {"raw_response": resp.text[:2000]}


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _error_message(resp: httpx.Response, path: str) -> str:
    fallback = f"Liongard returned HTTP {resp.status_code} for {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.lower().startswith("<"):
            return fallback  # an HTML error page, not useful to the agent
        return f"{fallback}: {text[:300]}" if text else fallback
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("Message") or payload.get("error") or payload.get("Error")
        if isinstance(message, dict):
            message = message.get("message") or message.get("Message")
        if message:
            return f"{fallback}: {str(message)[:500]}"
    return fallback
