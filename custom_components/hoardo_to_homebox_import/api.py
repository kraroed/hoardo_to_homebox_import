"""Minimal async Homebox REST client for Homebox 0.26+."""
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
        self._location_type_id: str | None = None

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with self._session.request(
                method, f"{self._base}{path}", headers=self._headers, timeout=TIMEOUT, **kwargs
            ) as resp:
                if resp.status in (401, 403):
                    raise HomeboxAuthError(f"Homebox authentication failed ({resp.status})")
                resp.raise_for_status()
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        except HomeboxAuthError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeboxError(str(err)) from err

    async def login(self) -> None:
        data = await self._request(
            "POST",
            "/users/login",
            json={"username": self._username, "password": self._password, "stayLoggedIn": False},
        )
        token = data.get("token")
        if not token:
            raise HomeboxAuthError("Homebox login response did not contain an authentication token")
        self._headers = {
            "Authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}"
        }

    async def location_tree(self) -> list[dict]:
        """Return the location tree (the old /locations/tree endpoint was removed in 0.26)."""
        return await self._request("GET", "/entities/tree")

    async def _get_location_type_id(self) -> str:
        """Find the entity type used for locations/containers."""
        if self._location_type_id:
            return self._location_type_id
        entity_types = await self._request("GET", "/entity-types")
        for entity_type in entity_types:
            if entity_type.get("isLocation"):
                self._location_type_id = entity_type["id"]
                return self._location_type_id
        raise HomeboxError(
            "This Homebox account has no location entity type. Create or enable a location type in Homebox and retry."
        )

    async def create_location(self, name: str, parent_id: str | None) -> str:
        """Create a location as an entity with a location entity type."""
        data = await self._request(
            "POST",
            "/entities",
            json={
                "name": name,
                "parentId": parent_id,
                "entityTypeId": await self._get_location_type_id(),
            },
        )
        return data["id"]

    async def create_item(self, name: str, quantity: int, description: str, location_id: str) -> str:
        """Create an inventory item as an entity under its parent location."""
        data = await self._request(
            "POST",
            "/entities",
            json={
                "name": name,
                "quantity": quantity,
                "description": description,
                "parentId": location_id,
            },
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
        await self._request("POST", f"/entities/{item_id}/attachments", data=form)
