from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BBLOCKS_", env_file=".env", extra="ignore")

    database_path: str = "./data/meta-register.db"

    meta_registry_index_url: str = "https://w3id.org/ogc/bblocks/meta-register.json"
    meta_registry_orgs_url: str = "https://w3id.org/ogc/bblocks/meta-register-orgs.json"

    crawl_interval_seconds: int = 3600
    crawl_on_startup: bool = True
    crawl_worker_pool_size: int = 3
    crawl_per_host_min_interval_seconds: float = 1.0

    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3

    # Pre-shared key required on all /admin/* requests via the X-Admin-Api-Key header.
    # Left unset (None) means /admin is unprotected -- fine for local dev, but must be set
    # before this backend is reachable from anywhere untrusted.
    admin_api_key: str | None = None

    # Comma-separated allowlists for the MCP server's DNS-rebinding protection (validated
    # against the Host/Origin headers of requests to /mcp). Left unset (None) means the MCP
    # endpoint has DNS-rebinding protection disabled -- fine for local dev, but must be set to
    # the backend's real public host(s) before /mcp is reachable from anywhere untrusted. The
    # MCP SDK's own localhost-only default (see mcp.server.fastmcp.server.FastMCP.__init__)
    # requires an explicit port in the Host header, which a reverse-proxied public hostname
    # normally won't have -- hence rolling our own instead of relying on that default.
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

    embedding_batch_size: int = 64
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
