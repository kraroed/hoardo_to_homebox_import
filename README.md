# Hoardo to Homebox Import

Home Assistant custom integration that imports a Hoardo CSV export, photos included, into Homebox.

## Install
HACS → Custom repositories → add this repo (type: Integration), or copy `custom_components/hoardo_to_homebox_import` into `/config/custom_components/`. Restart Home Assistant.

## Set up
Settings → Devices & Services → Add Integration → **Hoardo to Homebox Import**. Enter your Homebox URL, email and password.

## Import
- **UI:** open the integration → **Configure**, choose the CSV, type the room name, submit.
- **Action:** `hoardo_to_homebox_import.import_csv` with `path` (e.g. `/config/hoardo/Family_Room_inventory.csv`) and `room`.

Imports run in the background; a notification reports the result. Re-running skips items already imported.
Locations are created as `Room / Box (#n)`. Category, Lists and Notes go into the item description.
Photos are converted from AVIF to JPEG when Pillow can read AVIF; otherwise the original is uploaded.
