import httpx

from app.crawler.http import get_json


async def fetch_register(client: httpx.AsyncClient, register_url: str) -> dict:
    data = await get_json(client, register_url)
    if not isinstance(data, dict):
        raise ValueError(f"Expected register.json at {register_url} to be a JSON object")
    return data
