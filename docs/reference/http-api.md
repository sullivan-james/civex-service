# HTTP API

Everything the CLI can do is also available over HTTP, served under the `/api` prefix by `civex serve` (paths below omit that prefix — see [Server & web UI](../guides/server-and-web-ui.md) for how to start the server). This page is rendered from the same OpenAPI spec the running server exposes at `/openapi.json`, so it stays in sync with the code automatically.

The raw spec is also published alongside this page: [openapi.json](openapi.json). Paste it into [Swagger Editor](https://editor.swagger.io/), Postman, or an SDK generator if you'd rather work from the machine-readable version than this rendered page.

This reference doesn't include a "try it out" console — it's a static page with no server behind it, so there's nothing to call. Use `civex serve` and the live `/docs` Swagger UI for that.

[OAD(./openapi.json)]
