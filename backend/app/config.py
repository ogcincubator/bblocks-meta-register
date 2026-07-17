from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BBLOCKS_", env_file=".env", extra="ignore")

    database_path: str = "./data/meta-register.db"

    meta_registry_index_url: str = "https://w3id.org/ogc/bblocks/meta-register.json"
    meta_registry_orgs_url: str = "https://w3id.org/ogc/bblocks/meta-register-orgs.json"

    crawl_interval_seconds: int = 3600
    crawl_on_startup: bool = True
    crawl_worker_pool_size: int = 3
    crawl_per_host_min_interval_seconds: float = 2.0
    # Random jitter added on top of the min interval so per-host request timing isn't a
    # perfectly regular cadence -- see PerHostThrottle.wait() in app/crawler/http.py.
    crawl_per_host_jitter_seconds: float = 1.0

    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3

    # Separate from http_timeout_seconds: embedding requests hit a self-hosted model server that
    # may run CPU-only inference (no GPU), where a single embedding_batch_size-sized batch can
    # legitimately take well over the generic HTTP timeout -- especially now that concurrent
    # registers' embedding calls are serialized (see _ollama_request_lock in
    # app/search/embeddings.py) rather than racing each other for the same CPU.
    embedding_http_timeout_seconds: float = 120.0

    # Pre-shared key required on all /admin/* requests via the X-Admin-Api-Key header.
    # Left unset (None) means /admin is unprotected -- fine for local dev, but must be set
    # before this backend is reachable from anywhere untrusted.
    admin_api_key: str | None = None

    # Comma-separated allowlists for the MCP server's DNS-rebinding protection (validated
    # against the Host/Origin headers of requests to /mcp). Left unset (None) means the MCP
    # endpoint has DNS-rebinding protection disabled. Unlike admin_api_key below, this is not a
    # "must set before going public" flag: DNS rebinding only matters when a server sits behind
    # a trust boundary (localhost/internal-only) that a browser can still reach -- it protects
    # the gap between "network-reachable" and "meant to be reachable". This API is deliberately
    # public and unauthenticated (see the CORS allow_origins=["*"] comment in app/main.py), so
    # there's no such gap and no session/auth boundary for a rebinding attack to smuggle through
    # -- leaving this unset is the correct choice for this deployment, not just a dev shortcut.
    # If it's ever set, note the MCP SDK's own localhost-only default (see
    # mcp.server.fastmcp.server.FastMCP.__init__) requires an explicit port in the Host header,
    # which a reverse-proxied public hostname normally won't have -- hence rolling our own.
    mcp_allowed_hosts: str | None = None
    mcp_allowed_origins: str | None = None

    # "ollama" (default -- self-hosted, no external dependency) or "openai_compatible".
    embedding_provider: str = "ollama"
    embedding_dimensions: int = 768

    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text-v2-moe:latest"

    openai_compatible_base_url: str | None = None
    openai_compatible_embedding_model: str | None = None
    openai_compatible_api_key: str | None = None

    embedding_batch_size: int = 32
    search_keyword_candidates: int = 50
    search_semantic_candidates: int = 50
    # Users mostly describe a use case in natural language (often not English), not a curated
    # set of keywords -- the semantic pass is what actually understands that, so it dominates
    # the default (non-strict) hybrid merge; the keyword pass is a boost on top, not a gate.
    search_semantic_weight: float = 0.75

    @property
    def database_url(self) -> str:
        if self.database_path == ":memory:":
            return "sqlite+aiosqlite://"
        return f"sqlite+aiosqlite:///{self.database_path}"


settings = Settings()
