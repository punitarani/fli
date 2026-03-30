# Cloudflare MCP Deployment

This repository includes a Cloudflare deployment target for the HTTP MCP server:

* A small Worker in `src/index.ts`
* A single Cloudflare Container built from the repo `Dockerfile`
* Readiness checks via `GET /healthz`

This keeps the Python MCP tool surface unchanged while making the server deployable on Cloudflare.

## Architecture

* `ANY /mcp` is handled by the Worker and proxied to one named container instance: `shared`
* `GET /healthz` probes the container's `/mcp` endpoint with the required `Accept` header
* `GET /` returns deployment metadata and endpoint URLs
* `/mcp` is public; no Worker secret is required

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

For local overrides without editing `wrangler.jsonc`, export any of the keys listed in
`scripts/worker-env-keys.txt` and run:

```bash
make cloudflare-dev-vars
```

This writes `.dev.vars` for `wrangler dev`.

## Local Development

```bash
make cloudflare-dev
```

Cloudflare Containers local development requires Docker. Wrangler will build the root `Dockerfile` and run the Worker locally.

## Dry Run

```bash
make cloudflare-dry-run
```

This builds the Worker bundle and container image locally through `wrangler deploy --dry-run`.

## GitHub Actions CI/CD

The repo includes [`.github/workflows/ci-cd.yml`](../../.github/workflows/ci-cd.yml).

Behavior:

* Pull requests to `main` run the reusable Python test workflow, validate the Worker types, and run a Cloudflare dry run
* GitHub release publishes and manual workflow dispatches run the same checks, then deploy the Worker and container to Cloudflare

Required GitHub secrets:

* `CLOUDFLARE_API_TOKEN`
* `CLOUDFLARE_ACCOUNT_ID`

Optional GitHub repository or environment variables:

* `FLI_MCP_DEFAULT_PASSENGERS`
* `FLI_MCP_DEFAULT_CURRENCY`
* `FLI_MCP_DEFAULT_CABIN_CLASS`
* `FLI_MCP_DEFAULT_SORT_BY`
* `FLI_MCP_DEFAULT_DEPARTURE_WINDOW`
* `FLI_MCP_MAX_RESULTS`

The workflow reads those keys from `scripts/worker-env-keys.txt` and passes any non-empty values to
`wrangler deploy --var ...`, so GitHub-side overrides stay consistent with local `.dev.vars` generation.

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
URL with an MCP client that supports remote streamable HTTP servers.
