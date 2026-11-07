"""Hoardo CSV -> Homebox import logic."""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import HomeboxClient, HomeboxError

_LOGGER = logging.getLogger(__name__)


def _to_jpeg(data: bytes) -> bytes:
    from PIL import Image  # bundled with Home Assistant

    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _walk(nodes: list[dict], parent: str | None, out: dict) -> None:
    for node in nodes:
        if node.get("type", "location") == "location":
            out[(parent, node["name"])] = node["id"]
            _walk(node.get("children") or [], node["id"], out)


async def async_import(
    hass: HomeAssistant, client: HomeboxClient, store: Store, csv_text: str, room: str
) -> dict[str, Any]:
    """Import rows; returns counts and failure messages."""
    rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    state = await store.async_load() or {}
    done: dict[str, str] = state.get("done", {})
    slug = re.sub(r"[^a-z0-9]+", "-", room.lower())

    await client.login()
    locs: dict[tuple, str] = {}
    _walk(await client.location_tree(), None, locs)

    async def location(path: list[str]) -> str:
        parent = None
        for name in path:
            if (parent, name) not in locs:
                locs[(parent, name)] = await client.create_location(name, parent)
            parent = locs[(parent, name)]
        return parent  # type: ignore[return-value]

    result = {"imported": 0, "skipped": 0, "failed": 0, "errors": [], "photo_fallbacks": 0}
    for i, row in enumerate(rows):
        name = (row.get("Item") or "").strip()
        if not name:
            continue
        photo = (row.get("Photo") or "").strip()
        seg = photo.split("/")
        key = f"{slug}:{seg[-2] if len(seg) > 2 else f'row{i}'}"
        if key in done:
            result["skipped"] += 1
            continue

        box, num = (row.get("Box") or "").strip(), (row.get("Box #") or "").strip()
        label = f"{box} (#{num})" if box and num else box or (f"Box #{num}" if num else "")
        notes = "\n".join(
            x
            for x in [
                (row.get("Notes") or "").strip(),
                f"Category: {row['Category']}" if row.get("Category") else "",
                f"Lists: {row['Lists']}" if row.get("Lists") else "",
            ]
            if x
        )
        try:
            qty = int(float(row.get("Quantity") or 1))
        except ValueError:
            qty = 1
        try:
            loc_id = await location([room] + ([label] if label else []))
            item_id = await client.create_item(name[:255], qty, notes[:1000], loc_id)
            done[key] = item_id  # item exists now; record before the photo so a retry won't duplicate it
            await store.async_save({"done": done})
            if photo:
                raw = await client.download(photo)
                fname = f"{name[:60]}.jpg"
                try:
                    content, ctype = await hass.async_add_executor_job(_to_jpeg, raw), "image/jpeg"
                except Exception:  # noqa: BLE001 - e.g. Pillow without AVIF support
                    _LOGGER.warning("Could not convert photo for %s; uploading original", name)
                    result["photo_fallbacks"] += 1
                    content, ctype, fname = raw, "image/avif", f"{name[:60]}.avif"
                await client.attach_photo(item_id, fname, content, ctype)
            result["imported"] += 1
        except HomeboxError as err:
            result["failed"] += 1
            result["errors"].append(f"{name}: {err}")
            _LOGGER.error("Failed importing %s: %s", name, err)
    return result
