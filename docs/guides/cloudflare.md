# Cloudflare MCP Deployment

This repository includes a Cloudflare deployment target for the HTTP MCP server:

* A small Worker in `src/index.ts`
* A single Cloudflare Container built from the repo `Dockerfile`
* Bearer-token auth at the edge
* Readiness checks via `GET /healthz`

This keeps the Python MCP tool surface unchanged while making the server deployable on Cloudflare.

## Architecture

* `ANY /mcp` is handled by the Worker and proxied to one named container instance: `shared`
* `GET /healthz` probes the container's `/mcp` endpoint with the required `Accept` header
* `GET /` returns deployment metadata and endpoint URLs
* The Worker strips the edge `Authorization` header before proxying requests to the Python server

## Prerequisites

* Workers Paid plan with Containers enabled
* Docker running locally
* `npm`
* `wrangler login`

## Install

```bash
make cloudflare-install
```

This installs the Worker dependencies and generates `worker-configuration.d.ts` from `wrangler.jsonc`.

## Configure

Set the Worker secret used to protect `/mcp`:

```bash
npx wrangler secret put MCP_API_TOKEN
```

For local `wrangler dev`, use `.dev.vars`:

```bash
printf 'MCP_API_TOKEN=replace-me\n' > .dev.vars
```

The Worker passes these environment variables into the container:

* `HOST=0.0.0.0`
* `PORT=8000`
* `FLI_MCP_DEFAULT_PASSENGERS`
* `FLI_MCP_DEFAULT_CURRENCY`
* `FLI_MCP_DEFAULT_CABIN_CLASS`
* `FLI_MCP_DEFAULT_SORT_BY`
* `FLI_MCP_DEFAULT_DEPARTURE_WINDOW` if configured
* `FLI_MCP_MAX_RESULTS` if configured

To override the defaults, edit `vars` in `wrangler.jsonc` before deploying.

## Local Development

```bash
make cloudflare-dev
```

Cloudflare Containers local development requires Docker. Wrangler will build the root `Dockerfile` and run the Worker locally.

## Deploy

```bash
make cloudflare-deploy
```

On the first deploy, Cloudflare may take several minutes to provision the container image. During that time,
the Worker can respond with `503` from `/healthz` or `/mcp`.

## Smoke Test

Run these after `make cloudflare-dev` or after deploy against your `*.workers.dev` URL:

```bash
curl http://127.0.0.1:8787/

curl http://127.0.0.1:8787/healthz

curl \
  -H "Authorization: Bearer $MCP_API_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  http://127.0.0.1:8787/mcp
```

Expected behavior:

* `/` returns JSON metadata including `mcp_url`
* `/healthz` returns `200` when the container is ready
* `/mcp` returns a FastMCP transport response. A `400` with `Missing session ID` is a healthy readiness signal for a bare `GET`.

Use `make cloudflare-tail` to inspect Worker logs during local debugging or after deployment.

## Client Access

The deployed endpoint is a remote MCP server URL. Use the deployed `https://<worker>.<subdomain>.workers.dev/mcp`
URL with an MCP client that supports remote streamable HTTP servers, and include the bearer token configured via
`MCP_API_TOKEN`.
