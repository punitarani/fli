import { Container } from "@cloudflare/containers";
import type { DurableObject } from "cloudflare:workers";

const CONTAINER_ID = "shared";
const CONTAINER_PORT = "8000";
const CONTAINER_SLEEP_AFTER = "10m";
const MCP_ACCEPT_HEADER = "application/json, text/event-stream";
const MCP_PATH = "/mcp";

type WorkerEnv = Env & {
  MCP_API_TOKEN?: string;
  FLI_MCP_DEFAULT_PASSENGERS?: string;
  FLI_MCP_DEFAULT_CURRENCY?: string;
  FLI_MCP_DEFAULT_CABIN_CLASS?: string;
  FLI_MCP_DEFAULT_SORT_BY?: string;
  FLI_MCP_DEFAULT_DEPARTURE_WINDOW?: string;
  FLI_MCP_MAX_RESULTS?: string;
};

type ReadinessResult = {
  ok: boolean;
  status: number;
  message: string;
  details?: string;
};

export class FliMcpContainer extends Container<WorkerEnv> {
  defaultPort = 8000;
  sleepAfter = CONTAINER_SLEEP_AFTER;
  pingEndpoint = "container/mcp";

  constructor(ctx: DurableObject["ctx"], env: WorkerEnv) {
    super(ctx, env);
    this.envVars = buildContainerEnv(env);
  }
}

const handler = {
  async fetch(request: Request, env: WorkerEnv): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/") {
      return jsonResponse(
        {
          service: "fli-mcp",
          deployment_target: "cloudflare-containers",
          transport: "streamable-http",
          container_id: CONTAINER_ID,
          mcp_url: `${url.origin}${MCP_PATH}`,
          health_url: `${url.origin}/healthz`,
          requires_bearer_auth: true,
          configured: Boolean(env.MCP_API_TOKEN),
        },
        200,
      );
    }

    if (url.pathname === "/healthz") {
      if (request.method !== "GET") {
        return methodNotAllowed(["GET"]);
      }

      const readiness = await checkReadiness(env);
      return jsonResponse(readiness, readiness.status);
    }

    if (url.pathname === MCP_PATH || url.pathname === `${MCP_PATH}/`) {
      if (!isAuthorized(request, env)) {
        return unauthorizedResponse(env);
      }

      return proxyMcpRequest(request, env);
    }

    return jsonResponse(
      {
        error: "Not Found",
        message: "Use / for metadata, /healthz for readiness, or /mcp for the MCP endpoint.",
      },
      404,
    );
  },
};

export default handler;

function buildContainerEnv(env: WorkerEnv): Record<string, string> {
  const containerEnv: Record<string, string> = {
    HOST: "0.0.0.0",
    PORT: CONTAINER_PORT,
    FLI_MCP_DEFAULT_PASSENGERS: env.FLI_MCP_DEFAULT_PASSENGERS ?? "1",
    FLI_MCP_DEFAULT_CURRENCY: env.FLI_MCP_DEFAULT_CURRENCY ?? "USD",
    FLI_MCP_DEFAULT_CABIN_CLASS: env.FLI_MCP_DEFAULT_CABIN_CLASS ?? "ECONOMY",
    FLI_MCP_DEFAULT_SORT_BY: env.FLI_MCP_DEFAULT_SORT_BY ?? "CHEAPEST",
  };

  if (env.FLI_MCP_DEFAULT_DEPARTURE_WINDOW) {
    containerEnv.FLI_MCP_DEFAULT_DEPARTURE_WINDOW = env.FLI_MCP_DEFAULT_DEPARTURE_WINDOW;
  }

  if (env.FLI_MCP_MAX_RESULTS) {
    containerEnv.FLI_MCP_MAX_RESULTS = env.FLI_MCP_MAX_RESULTS;
  }

  return containerEnv;
}

function jsonResponse(payload: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

function methodNotAllowed(allow: string[]): Response {
  return jsonResponse(
    {
      error: "Method Not Allowed",
      allow,
    },
    405,
    { allow: allow.join(", ") },
  );
}

function unauthorizedResponse(env: WorkerEnv): Response {
  if (!env.MCP_API_TOKEN) {
    return jsonResponse(
      {
        ok: false,
        error: "MCP_API_TOKEN is not configured in Worker secrets.",
      },
      503,
    );
  }

  return jsonResponse(
    {
      ok: false,
      error: "Unauthorized",
      message: "Provide Authorization: Bearer <MCP_API_TOKEN>.",
    },
    401,
    { "www-authenticate": 'Bearer realm="fli-mcp"' },
  );
}

function isAuthorized(request: Request, env: WorkerEnv): boolean {
  if (!env.MCP_API_TOKEN) {
    return false;
  }

  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return false;
  }

  const provided = authorization.slice("Bearer ".length).trim();
  return timingSafeEqual(provided, env.MCP_API_TOKEN);
}

function timingSafeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  const maxLength = Math.max(leftBytes.length, rightBytes.length);

  let difference = leftBytes.length === rightBytes.length ? 0 : 1;

  for (let index = 0; index < maxLength; index += 1) {
    difference |= (leftBytes[index] ?? 0) ^ (rightBytes[index] ?? 0);
  }

  return difference === 0;
}

async function proxyMcpRequest(request: Request, env: WorkerEnv): Promise<Response> {
  const targetUrl = normalizeMcpUrl(request.url);
  const headers = new Headers(request.headers);
  headers.delete("authorization");

  const forwardedRequest = new Request(targetUrl, {
    method: request.method,
    headers,
    body: shouldForwardBody(request.method) ? request.body : undefined,
    redirect: "manual",
  });

  const response = await env.FLI_MCP.getByName(CONTAINER_ID).fetch(forwardedRequest);
  return normalizeContainerFailure(response);
}

function normalizeMcpUrl(input: string): string {
  const url = new URL(input);
  if (url.pathname === `${MCP_PATH}/`) {
    url.pathname = MCP_PATH;
  }
  return url.toString();
}

function shouldForwardBody(method: string): boolean {
  return method !== "GET" && method !== "HEAD";
}

async function checkReadiness(env: WorkerEnv): Promise<ReadinessResult> {
  try {
    const probeRequest = new Request(`https://container.internal${MCP_PATH}`, {
      method: "GET",
      headers: {
        accept: MCP_ACCEPT_HEADER,
      },
    });

    const response = await normalizeContainerFailure(
      await env.FLI_MCP.getByName(CONTAINER_ID).fetch(probeRequest),
    );
    const body = await response.text();

    if (response.status === 400 && body.includes("Missing session ID")) {
      return {
        ok: true,
        status: 200,
        message: "MCP endpoint is ready.",
      };
    }

    if (response.ok) {
      return {
        ok: true,
        status: 200,
        message: "MCP endpoint is ready.",
        details: body || undefined,
      };
    }

    if (response.status === 503) {
      return {
        ok: false,
        status: 503,
        message: "Container is provisioning or warming up.",
        details: body || undefined,
      };
    }

    return {
      ok: false,
      status: 503,
      message: "Container responded, but the MCP endpoint is not ready.",
      details: body || `Unexpected status: ${response.status}`,
    };
  } catch (error) {
    return {
      ok: false,
      status: 503,
      message: "Container is provisioning or warming up.",
      details: error instanceof Error ? error.message : String(error),
    };
  }
}

async function normalizeContainerFailure(response: Response): Promise<Response> {
  if (response.status !== 500 && response.status !== 503) {
    return response;
  }

  const body = await response.clone().text();
  if (!isContainerStartupFailure(body)) {
    return response;
  }

  return jsonResponse(
    {
      ok: false,
      error: "MCP container is provisioning or warming up.",
      details: body,
    },
    503,
  );
}

function isContainerStartupFailure(body: string): boolean {
  return (
    body.includes("Failed to start container") ||
    body.includes("There is no Container instance available") ||
    body.includes("No such container") ||
    body.includes("Network connection lost")
  );
}
