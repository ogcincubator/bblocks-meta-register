"""Stub OAuth 2.1 authorization server + protected-resource metadata.

This exists purely to satisfy Claude.ai's custom-connector flow, which attempts OAuth
Dynamic Client Registration even against MCP servers that advertise no auth at all
(https://github.com/anthropics/claude-ai-mcp/issues/457). It performs NO real
authentication: /authorize auto-approves every request with no login or consent UI, and
the tokens it issues are never validated by the actual bblocks-meta-register backend
(which is deliberately public/unauthenticated -- see backend/app/config.py). Do not point
this at anything that isn't already meant to be public and unauthenticated, and do not
mistake this for real access control.

Storage is in-memory only -- a container restart drops all registered clients, codes, and
tokens, forcing connected clients to redo the OAuth dance. That's an acceptable cost for a
stub; if it becomes annoying, put a volume behind a pickle/sqlite file instead of adding
real infrastructure.
"""

import base64
import hashlib
import os
import secrets
import time
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

# -- Configuration -------------------------------------------------------------------
# ISSUER is this stub's own identity -- it doubles as the path prefix under which
# /register, /authorize and /token are served (see ROUTER_PREFIX below), because RFC 8414
# metadata discovery inserts /.well-known/oauth-authorization-server *before* whatever
# path component the issuer URL has.
ISSUER = os.environ["OAUTH_STUB_ISSUER"]  # e.g. https://defs-dev.opengis.net/bblocks-oauth-stub
RESOURCE_URL = os.environ["OAUTH_STUB_RESOURCE_URL"]  # e.g. https://defs-dev.opengis.net/bblocks-meta-register-backend/mcp
ROUTER_PREFIX = "/" + ISSUER.split("/", 3)[-1] if ISSUER.count("/") > 2 else ""
ACCESS_TOKEN_TTL_SECONDS = int(os.environ.get("OAUTH_STUB_TOKEN_TTL_SECONDS", 90 * 24 * 3600))
AUTH_CODE_TTL_SECONDS = 300

app = FastAPI(title="bblocks-oauth-stub")

_clients: dict[str, dict] = {}
_codes: dict[str, dict] = {}
_refresh_tokens: dict[str, dict] = {}


def _b64url_sha256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# -- RFC 9728: OAuth 2.0 Protected Resource Metadata ----------------------------------
# Path is fixed by spec: /.well-known/oauth-protected-resource/<resource's own path>,
# resolved against the *resource's* origin (defs-dev.opengis.net), not this stub's.
@app.get("/.well-known/oauth-protected-resource/bblocks-meta-register-backend/mcp")
def protected_resource_metadata():
    return JSONResponse({
        "resource": RESOURCE_URL,
        "authorization_servers": [ISSUER],
        "bearer_methods_supported": ["header"],
    })


# -- RFC 8414: OAuth 2.0 Authorization Server Metadata ---------------------------------
@app.get(f"/.well-known/oauth-authorization-server{ROUTER_PREFIX}")
def authorization_server_metadata():
    return JSONResponse({
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    })


# -- RFC 7591: Dynamic Client Registration ---------------------------------------------
@app.post(f"{ROUTER_PREFIX}/register")
async def register(request: Request):
    body = await request.json()
    client_id = secrets.token_urlsafe(16)
    client = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "redirect_uris": body.get("redirect_uris", []),
        "token_endpoint_auth_method": "none",
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "response_types": body.get("response_types", ["code"]),
        "client_name": body.get("client_name", "unnamed-client"),
    }
    _clients[client_id] = client
    return JSONResponse(client, status_code=201)


# -- Authorization endpoint: auto-approves, no login/consent screen -------------------
@app.get(f"{ROUTER_PREFIX}/authorize")
def authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    state: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
):
    if response_type != "code":
        raise HTTPException(400, "unsupported response_type")
    client = _clients.get(client_id)
    if client is None:
        raise HTTPException(400, "unknown client_id")
    if client["redirect_uris"] and redirect_uri not in client["redirect_uris"]:
        raise HTTPException(400, "redirect_uri not registered for this client")
    if code_challenge_method != "S256":
        raise HTTPException(400, "only S256 code_challenge_method is supported")

    code = secrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "resource": resource,
        "expires_at": time.time() + AUTH_CODE_TTL_SECONDS,
    }
    sep = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{sep}code={code}"
    if state is not None:
        location += f"&state={state}"
    return RedirectResponse(location, status_code=302)


@app.post(f"{ROUTER_PREFIX}/token")
async def token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
):
    if grant_type == "authorization_code":
        entry = _codes.pop(code, None) if code else None
        if entry is None or entry["expires_at"] < time.time():
            raise HTTPException(400, "invalid_grant")
        if entry["redirect_uri"] != redirect_uri or entry["client_id"] != client_id:
            raise HTTPException(400, "invalid_grant")
        if not code_verifier or _b64url_sha256(code_verifier) != entry["code_challenge"]:
            raise HTTPException(400, "invalid_grant: PKCE verification failed")
        return _issue_token(entry["client_id"])

    if grant_type == "refresh_token":
        entry = _refresh_tokens.get(refresh_token) if refresh_token else None
        if entry is None:
            raise HTTPException(400, "invalid_grant")
        return _issue_token(entry["client_id"], reuse_refresh=refresh_token)

    raise HTTPException(400, "unsupported_grant_type")


def _issue_token(client_id: str, reuse_refresh: Optional[str] = None):
    access_token = secrets.token_urlsafe(32)
    refresh = reuse_refresh or secrets.token_urlsafe(32)
    _refresh_tokens[refresh] = {"client_id": client_id}
    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": refresh,
    })
