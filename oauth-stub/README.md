# bblocks-oauth-stub

A no-op OAuth 2.1 authorization server that exists solely to satisfy Claude.ai's custom
MCP connector, which attempts Dynamic Client Registration even against MCP servers that
advertise no auth at all ([anthropics/claude-ai-mcp#457](https://github.com/anthropics/claude-ai-mcp/issues/457)).
It performs no real authentication or access control -- see the docstring in `main.py`.

## Deploying

`.github/workflows/oauth-stub-ci.yml` builds and pushes this image to
`ghcr.io/ogcincubator/bblocks-meta-register/oauth-stub`, same as `backend-ci.yml`/
`frontend-ci.yml` do for their images. `docker-compose.prod.yml` already has an
`oauth-stub` service pulling that image; it needs two env vars set in `.env` alongside the
compose file:

```
OAUTH_STUB_ISSUER=https://defs-dev.opengis.net/bblocks-oauth-stub
OAUTH_STUB_RESOURCE_URL=https://defs-dev.opengis.net/bblocks-meta-register-backend/mcp
```

## Apache reverse-proxy rules

Add to the HTTPS vhost for `defs-dev.opengis.net` (**not** the plain-HTTP one -- recall it
was seen 403-ing `.well-known/*` outright; confirm these `ProxyPass` lines take precedence
over whatever dotfile-deny rule causes that, or add them to the HTTPS vhost only, which is
sufficient since OAuth traffic must be HTTPS anyway per spec). Three rules, matching the
three URL shapes the OAuth flow needs -- nothing else on the domain (`/prez/`, etc.) is
touched:

```apache
# RFC 9728 protected-resource metadata for the MCP resource -- must live at this exact
# path because well-known discovery is always resolved against the *resource's* own
# origin (defs-dev.opengis.net), not the stub's.
ProxyPass        "/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp" "http://127.0.0.1:8080/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp"
ProxyPassReverse "/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp" "http://127.0.0.1:8080/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp"

# RFC 8414 authorization-server metadata -- path suffix must match the stub's issuer path
# (OAUTH_STUB_ISSUER's path component, /bblocks-oauth-stub below).
ProxyPass        "/.well-known/oauth-authorization-server/bblocks-oauth-stub" "http://127.0.0.1:8080/.well-known/oauth-authorization-server/bblocks-oauth-stub"
ProxyPassReverse "/.well-known/oauth-authorization-server/bblocks-oauth-stub" "http://127.0.0.1:8080/.well-known/oauth-authorization-server/bblocks-oauth-stub"

# /register, /authorize, /token -- all served under the issuer's own path prefix.
ProxyPass        "/bblocks-oauth-stub/" "http://127.0.0.1:8080/bblocks-oauth-stub/"
ProxyPassReverse "/bblocks-oauth-stub/" "http://127.0.0.1:8080/bblocks-oauth-stub/"
```

Port `8080` above assumes the container is reachable on the host at that port (e.g. via
the `ports:` mapping in the compose snippet) -- adjust to match wherever it actually ends
up bound (a docker network alias instead of `127.0.0.1:8080` if Apache and the container
share a network).

## Local test

```bash
docker build -t bblocks-oauth-stub oauth-stub/
docker run --rm -p 8080:8080 \
  -e OAUTH_STUB_ISSUER=http://localhost:8080/bblocks-oauth-stub \
  -e OAUTH_STUB_RESOURCE_URL=http://localhost:8000/mcp \
  bblocks-oauth-stub

curl -s http://localhost:8080/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp
curl -s http://localhost:8080/.well-known/oauth-authorization-server/bblocks-oauth-stub
curl -s -X POST http://localhost:8080/bblocks-oauth-stub/register -H 'Content-Type: application/json' -d '{"client_name":"test","redirect_uris":["http://localhost:9999/cb"]}'
```
