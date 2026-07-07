import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from app.crawler.http import get_json

logger = logging.getLogger(__name__)


@dataclass
class OrgInfo:
    org_id: str
    name: str
    description: str | None
    url: str | None
    maintainers: list[dict]


@dataclass
class RegisterInfo:
    register_id: str  # "org/register", the meta-registry alias without the leading "@"
    org_id: str
    name: str  # last path segment, e.g. "main"
    register_url: str


@dataclass
class Discovery:
    orgs: list[OrgInfo]
    registers: list[RegisterInfo]


def _parse_orgs(raw: dict) -> list[OrgInfo]:
    orgs = []
    for org_id, info in raw.items():
        orgs.append(
            OrgInfo(
                org_id=org_id,
                name=info.get("name", org_id),
                description=info.get("description"),
                url=info.get("url"),
                maintainers=info.get("maintainers", []),
            )
        )
    return orgs


def _parse_registers(raw: dict) -> list[RegisterInfo]:
    """Parse index.json's alias -> register_url map. Tolerates non-`@org/register` keys
    (real-world index.json has a stray "default" key) by skipping anything that doesn't
    match the expected shape."""
    registers = []
    for alias, register_url in raw.items():
        if not isinstance(alias, str) or not alias.startswith("@") or "/" not in alias:
            logger.debug("Skipping non-alias index.json entry: %r", alias)
            continue
        org_id, name = alias[1:].split("/", 1)
        registers.append(
            RegisterInfo(register_id=f"{org_id}/{name}", org_id=org_id, name=name, register_url=register_url)
        )
    return registers


async def discover(client: httpx.AsyncClient) -> Discovery:
    index_raw, orgs_raw = await get_json(client, settings.meta_registry_index_url), await get_json(
        client, settings.meta_registry_orgs_url
    )
    if not isinstance(index_raw, dict) or not isinstance(orgs_raw, dict):
        raise ValueError("Expected index.json and orgs.json to both be JSON objects")
    return Discovery(orgs=_parse_orgs(orgs_raw), registers=_parse_registers(index_raw))
