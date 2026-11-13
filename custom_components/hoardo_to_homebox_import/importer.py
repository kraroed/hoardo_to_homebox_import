"""Hoardo CSV -> Homebox import logic."""
from __future__ import annotations

import csv
import io
import logging
import mimetypes
import re
from typing import Any
from urllib.parse import urlsplit

from .api import HomeboxClient, HomeboxError

_LOGGER = logging.getLogger(__name__)


def _to_jpeg(data: bytes) -> bytes:
    """Convert an image to JPEG when Pillow supports its format."""
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _original_photo_type(data: bytes, url: str) -> tuple[str, str]:
    """Identify the original image type for a safe, correctly labelled fallback."""
    signatures = (
        (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
        (b"GIF87a", "image/gif", ".gif"),
        (b"GIF89a", "image/gif", ".gif"),
        (b"RIFF", "image/webp", ".webp"),
        (b"BM", "image/bmp", ".bmp"),
    )
    for signature, content_type, extension in signatures:
        if data.startswith(signature) and (signature != b"RIFF" or data[8:12] == b"WEBP"):
            return content_type, extension
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif", ".avif"
    content_type, _ = mimetypes.guess_type(urlsplit(url).path)
    if content_type and content_type.startswith("image/"):
        return content_type, mimetypes.guess_extension(content_type) or ".img"
    return "application/octet-stream", ".bin"


async def _attach_photo(
    hass: Any, client: HomeboxClient, item_id: str, item_name: str, photo_url: str
) -> bool:
    """Attach a photo; return True when the original format had to be retained."""
    raw = await client.download(photo_url)
    try:
        content = await hass.async_add_executor_job(_to_jpeg, raw)
    except Exception:  # noqa: BLE001 - Pillow may be absent or lack format support
        content_type, extension = _original_photo_type(raw, photo_url)
        _LOGGER.warning("Could not convert photo for %s; uploading original as %s", item_name, content_type)
        await client.attach_photo(
            item_id, f"{item_name[:60]}{extension}", raw, content_type
        )
        return True
    await client.attach_photo(item_id, f"{item_name[:60]}.jpg", content, "image/jpeg")
    return False


def _walk(nodes: list[dict], parent: str | None, out: dict) -> None:
    """Index location-tree nodes; /entities/tree returns locations by default."""
    for node in nodes:
        node_id = node.get("id")
        name = node.get("name")
        if node_id and name:
            out[(parent, name)] = node_id
            _walk(node.get("children") or [], node_id, out)


async def async_import(
    hass: Any, client: HomeboxClient, store: Any, csv_text: str, room: str
) -> dict[str, Any]:
    """Import rows; preserve item IDs and retry photos that failed previously."""
    rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    state = await store.async_load() or {}
    done: dict[str, str] = state.get("done", {})
    # Keep this separate from "done" so older storage entries automatically retry
    # a photo once, without recreating the Homebox item.
    photos_done: set[str] = set(state.get("photos_done", []))
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

    async def save_state() -> None:
        await store.async_save({"done": done, "photos_done": sorted(photos_done)})

    result = {
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "photo_failed": 0,
        "photos_retried": 0,
        "errors": [],
        "photo_fallbacks": 0,
    }
    for i, row in enumerate(rows):
        name = (row.get("Item") or "").strip()
        if not name:
            continue
        photo = (row.get("Photo") or "").strip()
        seg = photo.split("/")
        key = f"{slug}:{seg[-2] if len(seg) > 2 else f'row{i}'}"

        if key in done:
            result["skipped"] += 1
            if photo and key not in photos_done:
                try:
                    if await _attach_photo(hass, client, done[key], name, photo):
                        result["photo_fallbacks"] += 1
                except HomeboxError as err:
                    result["photo_failed"] += 1
                    result["errors"].append(f"{name} (photo retry): {err}")
                    _LOGGER.error("Failed retrying photo for %s: %s", name, err)
                else:
                    photos_done.add(key)
                    await save_state()
                    result["photos_retried"] += 1
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
        except (ValueError, TypeError):
            qty = 1
        try:
            loc_id = await location([room] + ([label] if label else []))
            item_id = await client.create_item(name[:255], qty, notes[:1000], loc_id)
        except HomeboxError as err:
            result["failed"] += 1
            result["errors"].append(f"{name}: {err}")
            _LOGGER.error("Failed importing %s: %s", name, err)
            continue

        # Persist the created item before attempting its photo. If the photo fails,
        # the next import can resume against this ID rather than creating a duplicate.
        done[key] = item_id
        await save_state()
        result["imported"] += 1
        if photo:
            try:
                if await _attach_photo(hass, client, item_id, name, photo):
                    result["photo_fallbacks"] += 1
            except HomeboxError as err:
                result["photo_failed"] += 1
                result["errors"].append(f"{name} (photo): {err}")
                _LOGGER.error("Failed attaching photo for %s: %s", name, err)
            else:
                photos_done.add(key)
                await save_state()
    return result
