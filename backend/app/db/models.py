import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    maintainers: Mapped[list[dict]] = mapped_column(JSON, default=list)

    registers: Mapped[list["Register"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class Register(Base):
    __tablename__ = "registers"

    # Full alias, e.g. "ogc/main"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    register_url: Mapped[str] = mapped_column(String, unique=True)
    viewer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # `modified` timestamp as published by register.json, used for the cheap
    # register-level change-detection skip -- kept as the raw string, not parsed,
    # since it's only ever compared for equality against the next fetch.
    modified: Mapped[str | None] = mapped_column(String, nullable=True)
    last_crawled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_crawl_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Admin-only lifecycle status -- "pending" | "crawling" | "ready" | "failed". Distinct from
    # last_crawl_status (which only reflects the outcome of the *last completed* attempt): this
    # is set to "crawling" for the duration of a run, so a stuck/crashed crawl is visible as a
    # register stuck in "crawling" rather than silently showing its last known-good status.
    # Never exposed via the public API/MCP -- see app/api/admin.py.
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")

    org: Mapped["Org"] = relationship(back_populates="registers")
    bblocks: Mapped[list["Bblock"]] = relationship(back_populates="register", cascade="all, delete-orphan")


class Bblock(Base):
    __tablename__ = "bblocks"

    # itemIdentifier, globally unique by convention -- enforced by identifier-conflict
    # rejection in the crawler indexer, not by uniqueness alone (see identifier_conflicts).
    id: Mapped[str] = mapped_column(String, primary_key=True)
    register_id: Mapped[str] = mapped_column(ForeignKey("registers.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    abstract: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    item_class: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    date_time_addition: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_last_change: Mapped[str | None] = mapped_column(String, nullable=True)

    # Presence/absence badges -- register.json's `schema`/`shaclShapes` are objects keyed
    # by media type (not a single URL), so presence is "object/array is non-empty", stored
    # as a precomputed boolean rather than re-derived from schema_urls/shacl_shapes_urls on
    # every read.
    has_schema: Mapped[bool] = mapped_column(default=False)
    has_ld_context: Mapped[bool] = mapped_column(default=False)
    has_shacl_shapes: Mapped[bool] = mapped_column(default=False)
    schema_urls: Mapped[dict] = mapped_column(JSON, default=dict)
    ld_context_url: Mapped[str | None] = mapped_column(String, nullable=True)
    shacl_shapes_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    sources: Mapped[list[dict]] = mapped_column(JSON, default=list)

    register: Mapped["Register"] = relationship(back_populates="bblocks")
