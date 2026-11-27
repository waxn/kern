# Collector

Anything that can make an HTTP request can report numbers here:

```sh
curl -X POST https://<your server>/<path>/api/ingest \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"source": "laptop", "metric": "tokens", "value": 1234}'
```

`/api/ingest` is a *public path* in the app's Kern settings: it works without signing in to Kern,
and the app checks the token itself. Everything else (the dashboard) stays private.

The token is `INGEST_TOKEN` from the app's environment variables (Kern → the app → Settings), or one
the app makes up on first start and shows on the dashboard.
