"""Minimal async Homebox REST client."""
from __future__ import annotations

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=60)


class HomeboxError(Exception):
    """Cannot talk to Homebox."""


class HomeboxAuthError(HomeboxError):
    """Bad credentials."""


class HomeboxClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, username: str, password: str) -> None:
        url = url.strip().rstrip("/")
        if url.endswith("/api"):
            url = url[:-4]
        self._base = f"{url}/api/v1"
        self._session = session
        self._username = username
        self._password = password
        self._headers: dict[str, str] = {}

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with self._session.request(
                method, f"{self._base}{path}", headers=self._headers, timeout=TIMEOUT, **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    raise HomeboxAuthError(f"{resp.status} from {path}")
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            if isinstance(err, HomeboxError):
                raise
            raise HomeboxError(str(err)) from err

    async def login(self) -> None:
        data = await self._request(
            "POST",
            "/users/login",
            json={"username": self._username, "password": self._password, "stayLoggedIn": False},
        )
        self._headers = {"Authorization": data["token"]}

    async def location_tree(self) -> list[dict]:
        return await self._request("GET", "/locations/tree")

    async def create_location(self, name: str, parent_id: str | None) -> str:
        data = await self._request("POST", "/locations", json={"name": name, "parentId": parent_id})
        return data["id"]

    async def create_item(self, name: str, quantity: int, description: str, location_id: str) -> str:
        data = await self._request(
            "POST",
            "/items",
            json={"name": name, "quantity": quantity, "description": description, "locationId": location_id},
        )
        return data["id"]

    async def download(self, url: str) -> bytes:
        try:
            async with self._session.get(url, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeboxError(f"photo download failed: {err}") from err

    async def attach_photo(self, item_id: str, filename: str, content: bytes, content_type: str) -> None:
        form = aiohttp.FormData()
        form.add_field("file", content, filename=filename, content_type=content_type)
        form.add_field("type", "photo")
        form.add_field("primary", "true")
        form.add_field("name", filename)
        await self._request("POST", f"/items/{item_id}/attachments", data=form)
