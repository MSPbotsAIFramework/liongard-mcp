# Liongard MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Liongard](https://www.liongard.com) API (v1 and v2),
the platform MSPs use to inspect and document the systems they manage. It lets an AI agent read
environments (customers), agents, inspectors and launchpoints, systems and their latest data,
detections (changes between inspections), metrics and their values, the inspection timeline and
the identity / device inventory and, on explicit request, create environments and launchpoints,
run an inspection, or (with confirmation) delete an agent.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Liongard-Api-Key` | Yes | string | none | `AccessKeyID:AccessKeySecret`, or its base64 | The access token pair | `your-key-id:your-secret` |
| `X-Liongard-Instance` | Yes | string | none | instance name (or its host) | The `us1` in `https://us1.app.liongard.com` | `us1` |

Where to get them: in Liongard open the profile menu > **Account Settings** > **Access Tokens** and
generate a token for a user created for the integration; copy the Access Key ID and Secret (the
secret is shown once). Liongard roles of that user limit what the agent can see.

How they are used: every call goes to `https://{instance}.app.liongard.com/api/v1|v2/...` with
`X-ROAR-API-KEY: base64(AccessKeyID:AccessKeySecret)` (a key given as `id:secret` is encoded here;
an already encoded key is sent as is). Liongard answers with a redirect first, which is followed.

A request to `/mcp` without both headers gets HTTP 401; an invalid instance gets HTTP 400.

## Tools

All tools return a JSON string. Lists take `page` (from 1) and `pageSize` (default 50, max
200) and return `{count, total, page, has_more, offset, next_offset}`. To read on, pass
`offset: next_offset` (a record position that overrides `page`): when a page is too large for one
response and is cut, `next_offset` starts right after the last record returned, which no page number can.
**write** marks tools that change data; **confirm** marks the delete, which also needs `confirm: true`.

| Area | Tools |
|---|---|
| Overview | `liongard_navigate` (**domain**) |
| Environments | `liongard_environments_list`, `liongard_environments_get` (**id**), `liongard_environments_count`, `liongard_environments_related` (**id**); **write**: `liongard_environments_create` (**Name**, Description, Tier, ShortName, Parent; Status, Visible accepted and ignored) |
| Agents | `liongard_agents_list`; **confirm**: `liongard_agents_delete` (**id**) |
| Inspections | `liongard_inspections_inspectors`, `liongard_inspections_launchpoints`; **write**: `liongard_inspections_create_launchpoint` (**Name**, **InspectorID**, **EnvironmentID**, AgentID, Schedule, Config, SecureConfig), `liongard_inspections_run` (**launchpointId**) |
| Systems | `liongard_systems_list`, `liongard_systems_get` (**id**, include_data) |
| Detections | `liongard_detections_list` (startDate, endDate, filters), `liongard_detections_get` (**id**) |
| Metrics | `liongard_metrics_list`, `liongard_metrics_evaluate` (MetricIDs, EnvironmentIDs), `liongard_metrics_evaluate_systems` (SystemIDs, MetricIDs, EnvironmentIDs) |
| Timeline | `liongard_timeline_list` |
| Inventory | `liongard_inventory_identities` (**environment**, filters), `liongard_inventory_identity_get` (**id**), `liongard_inventory_devices` (**environment**, filters), `liongard_inventory_device_get` (**id**) |

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "unauthorized", "message": "Liongard returned HTTP 401 for v2/environments", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Reads are retried with backoff on 429, 5xx and network errors;
writes only on 429.

## Run locally

```bash
uv sync
uv run python -m liongard_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t liongard-mcp:dev .
docker run --rm -p 8080:8080 liongard-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). Credentials are never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Liongard-Api-Key: your-key-id:your-secret" \
  -H "X-Liongard-Instance: us1" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# detections since a date
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Liongard-Api-Key: your-key-id:your-secret" \
  -H "X-Liongard-Instance: us1" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"liongard_detections_list","arguments":{"startDate":"2026-10-01T00:00:00Z"}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (24).** Kept as is because the tool names are an existing contract.
- **Result size exception (SOP 2.5).** `liongard_metrics_list` has no paging parameters, so it still
  reads up to 2000 metrics in one call; results are still cut to 20,000 characters with a truncation notice.
- **API source.** Liongard's published OpenAPI documents (API v1 and v2, linked from
  docs.liongard.com).
- **Fixed calls.** Running an inspection is `GET /v1/launchpoints/{id}/run` (older versions used
  POST); metric evaluation is `POST /v2/metrics/evaluate` with `Metrics` and an environment filter
  and `POST /v2/metrics/evaluate/systems` with `Systems` (older versions called
  `/metrics-evaluate` routes with fields the API does not read); a single system is looked up with
  a v1 `conditions[]` filter (there is no `GET /systems/{id}`), and `include_data` adds its latest
  inspection data; creating a launchpoint sends the fields the API requires (alias, inspector,
  environment, agent, schedule, start time, config).
- **Required by the API, so now checked:** `MetricIDs` for evaluate, `SystemIDs` for
  evaluate_systems, `AgentID` for creating a launchpoint (each optional in the schema for
  compatibility, reported when missing).
- **Accepted but ignored**: `Status` and `Visible` on environment create are kept for
  compatibility but not sent; Liongard's create body (v1 and v2 OpenAPI) has no such fields.
- **Paging.** v1 lists (inspectors, launchpoints, systems) come back whole and are paged here; v2
  lists are paged by Liongard.
- **Not included**: the detection "card" UI resource of older versions (an MCP Apps HTML view);
  the tools return the same data as JSON.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
