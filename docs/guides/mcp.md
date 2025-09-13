## MCP Server (FastMCP)

This project exposes flight search tools via a FastMCP server. You can run it over STDIO (default) or the streamable HTTP transport.

### Run over STDIO

Use the existing console script:

```bash
fli-mcp
```

### Run over HTTP (streamable)

Use the new HTTP entrypoint. By default it binds to `127.0.0.1:8000`.

```bash
fli-mcp-http
```

You can override host/port by calling the function directly in Python:

```python
from fli.mcp import run_http

run_http(host="0.0.0.0", port=8000)
```

Once running, the MCP endpoint is served at `/mcp/`, for example: `http://127.0.0.1:8000/mcp/`.
