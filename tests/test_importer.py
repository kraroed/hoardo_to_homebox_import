"""Regression tests for resumable Hoardo photo imports."""
import asyncio
from unittest.mock import patch

from custom_components.hoardo_to_homebox_import import importer
from custom_components.hoardo_to_homebox_import.api import HomeboxError


CSV = """Item,Photo,Box,Box #,Notes,Category,Lists,Quantity
Camping lantern,https://photos.example/items/lantern/photo.avif,Camping,2,LED lantern,Outdoor,Camping,1
"""


class FakeStore:
    def __init__(self):
        self.state = None

    async def async_load(self):
        return self.state

    async def async_save(self, state):
        self.state = {
            "done": dict(state["done"]),
            "photos_done": list(state["photos_done"]),
        }


class FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeClient:
    def __init__(self, fail_first_photo=False):
        self.fail_first_photo = fail_first_photo
        self.login_calls = 0
        self.created_items = []
        self.download_calls = 0
        self.attach_calls = []

    async def login(self):
        self.login_calls += 1

    async def location_tree(self):
        return []

    async def create_location(self, name, parent_id):
        return f"location-{name}"

    async def create_item(self, name, quantity, description, location_id):
        item_id = f"item-{len(self.created_items) + 1}"
        self.created_items.append(item_id)
        return item_id

    async def download(self, url):
        self.download_calls += 1
        return b"fake-image-bytes"

    async def attach_photo(self, item_id, filename, content, content_type):
        self.attach_calls.append((item_id, filename, content, content_type))
        if self.fail_first_photo and len(self.attach_calls) == 1:
            raise HomeboxError("simulated attachment failure")


def test_failed_photo_is_retried_without_creating_duplicate_item():
    async def scenario():
        hass = FakeHass()
        store = FakeStore()
        client = FakeClient(fail_first_photo=True)

        with patch.object(importer, "_to_jpeg", return_value=b"jpeg-bytes"):
            first = await importer.async_import(hass, client, store, CSV, "Garage")
            assert first["imported"] == 1
            assert first["failed"] == 0
            assert first["photo_failed"] == 1
            assert store.state["done"]["garage:lantern"] == "item-1"
            assert "garage:lantern" not in store.state["photos_done"]

            second = await importer.async_import(hass, client, store, CSV, "Garage")
            assert second["imported"] == 0
            assert second["skipped"] == 1
            assert second["photos_retried"] == 1
            assert second["photo_failed"] == 0
            assert client.created_items == ["item-1"]
            assert store.state["photos_done"] == ["garage:lantern"]

            third = await importer.async_import(hass, client, store, CSV, "Garage")
            assert third["photos_retried"] == 0
            assert client.created_items == ["item-1"]
            assert client.download_calls == 2

    asyncio.run(scenario())


def test_original_photo_fallback_uses_detected_content_type_and_extension():
    async def scenario():
        hass = FakeHass()
        store = FakeStore()
        client = FakeClient()

        with patch.object(importer, "_to_jpeg", side_effect=OSError("unsupported image")):
            result = await importer.async_import(hass, client, store, CSV, "Garage")

        assert result["imported"] == 1
        assert result["photo_fallbacks"] == 1
        assert client.attach_calls[0][1] == "Camping lantern.avif"
        assert client.attach_calls[0][3] == "image/avif"

    # A minimal AVIF file-type box is sufficient to exercise format detection.
    original_download = FakeClient.download

    async def avif_download(self, url):
        self.download_calls += 1
        return b"\x00\x00\x00\x18ftypavif" + b"\x00" * 16

    with patch.object(FakeClient, "download", avif_download):
        asyncio.run(scenario())
