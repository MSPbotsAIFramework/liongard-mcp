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
"""Shared argument types, paging / filter helpers and the error-handling wrapper."""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, get_args

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import LiongardClient, LiongardError
from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger("liongard_mcp.tools")

ClientFactory = Callable[[], LiongardClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured", "Liongard credentials are missing for this request (X-Liongard-Api-Key, X-Liongard-Instance).", False
)

RecordId = Annotated[int, Field(description="Record id.", ge=1)]
Page = Annotated[int | None, Field(description="Page number, starting at 1.", ge=1)]
PageSize = Annotated[int | None, Field(description=f"Records per page (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[
    int | None,
    Field(description="Record position to start from (0-based, overrides page); pass next_offset from the previous result.", ge=0),
]
Filters = Annotated[
    list[dict[str, Any]] | None,
    Field(description='Liongard filter objects, e.g. [{"FilterBy": "Hostname", "Op": "contains", "Value": "PC"}].'),
]
Confirm = Annotated[bool | None, Field(description="Must be true, set only after the user approved this exact action.")]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None and v != "" and v != []}


def pagination(page: int | None, page_size: int | None) -> dict[str, int]:
    return {"Page": page or 1, "PageSize": page_size or DEFAULT_PAGE_SIZE}


def locate(offset: int | None, page: int | None, page_size: int | None) -> tuple[int, int, int]:
    """(page, page size, start) for a read from record ``start``.

    Liongard pages by number only, so a position is reached by asking for the page that
    holds it (same page size) and skipping the records before it.
    """
    size = page_size or DEFAULT_PAGE_SIZE
    start = offset if offset is not None else ((page or 1) - 1) * size
    return start // size + 1, size, start


def v2_page(payload: Any, key: str, number: int | None = None, size: int | None = None, start: int | None = None) -> dict:
    """A v2 list: {Data | <array>, Pagination: {TotalRows, HasMoreRows, CurrentPage, TotalPages, PageSize}}.

    With ``number`` (the page requested) the records from ``start`` on are returned, plus
    ``offset`` and ``next_offset``, which continues right after the last record returned, also
    when the result is cut to fit the size limit (a page number cannot: the rest of a cut page
    is on no other page). ``size`` None means the page size Liongard reports (else the default).
    """
    rows: Any = payload
    paging: dict = {}
    if isinstance(payload, dict):
        paging = payload.get("Pagination") or payload.get("pagination") or {}
        rows = next((payload[k] for k in ("Data", "data", "Items", "items", "Results", "results") if isinstance(payload.get(k), list)), None)
        if rows is None:
            rows = next((v for v in payload.values() if isinstance(v, list)), [])
    rows = rows if isinstance(rows, list) else []
    result: dict[str, Any] = {
        key: rows,
        "count": len(rows),
        "total": paging.get("TotalRows"),
        "page": paging.get("CurrentPage"),
        "has_more": bool(paging.get("HasMoreRows")) if paging else None,
    }
    if number is not None:
        if size is None:
            reported = paging.get("PageSize")
            size = reported if isinstance(reported, int) and reported > 0 else DEFAULT_PAGE_SIZE
        first = (number - 1) * size
        start = first if start is None else start
        more = bool(paging.get("HasMoreRows")) if paging else len(rows) >= size
        rows = rows[start - first :]
        result |= {
            key: rows,
            "count": len(rows),
            "offset": start,
            "next_offset": start + len(rows) if more else None,
            "_resume": {"key": "next_offset", "start": start},
        }
    return compact(result)


def local_page(rows: Any, key: str, page: int | None, page_size: int | None, offset: int | None = None) -> dict:
    """Page a v1 list (the v1 API returns the whole set) on this side.

    Same shape as a v2 page: the records from ``offset`` (or the page start) to the end of
    the page that holds it, with ``next_offset`` right after the last record returned.
    """
    rows = rows if isinstance(rows, list) else []
    number, size, start = locate(offset, page, page_size)
    chunk = rows[start : number * size]
    more = number * size < len(rows)
    result = {key: chunk, "count": len(chunk), "total": len(rows), "page": number, "has_more": more, "offset": start}
    if more:
        result["next_offset"] = start + len(chunk)
    return result | {"_resume": {"key": "next_offset", "start": start}}


def not_confirmed_result(action: str) -> dict:
    return {
        "done": False,
        "action": action,
        "message": "Not done. Describe this action to the user and call again with confirm: true only after they approve it.",
    }


def condition(path: str, op: str, value: Any) -> str:
    """One v1 `conditions[]` filter value."""
    return json.dumps({"path": path, "op": op, "value": value})


def enum_value(value: Any, choices: Any) -> Any:
    """Canonical spelling of a case-insensitive match in ``choices`` (a Literal type).

    Any other value passes through unchanged, so the API decides (older callers sent free text).
    """
    if not isinstance(value, str):
        return value
    wanted = value.strip().lower()
    return next((c for c in get_args(choices) if isinstance(c, str) and c.lower() == wanted), value)


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[LiongardClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        value = await action(client)
    except LiongardError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if value is None:
        value = {"done": True}
    return value if isinstance(value, str) else dump_json_capped(value)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
