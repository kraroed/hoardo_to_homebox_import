# Hoardo to Homebox Import

Import your Hoardo inventory export into [Homebox](https://github.com/sysadminsmedia/homebox) from Home Assistant. The integration creates Homebox locations and inventory entities, preserves Hoardo item details, and attaches item photos when available.

[![Open your Home Assistant instance and add this integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hoardo_to_homebox_import)

## Features

- Import a Hoardo CSV export into Homebox.
- Create a top-level room location and nested box locations automatically.
- Import item name, quantity, notes, category, and list information.
- Download and attach item photos.
- Track completed rows in Home Assistant storage so repeat imports skip items already imported.
- Run an import from the integration options or from a Home Assistant action.

## Requirements

- Home Assistant with support for custom integrations.
- Homebox **0.26.0 or newer**.
- A Homebox account that can create locations, inventory entities, and attachments.
- A Hoardo CSV export. Photo URLs in the export must be reachable from Home Assistant.

## Installation

### Home Assistant Marketplace

1. Open **Settings → Apps / Marketplace** (the exact menu label can vary by Home Assistant version).
2. Add this repository as a custom integration repository: `https://github.com/kraroed/hoardo_to_homebox_import`.
3. Install **Hoardo to Homebox Import**.
4. Restart Home Assistant if prompted.

### Manual installation

1. Copy `custom_components/hoardo_to_homebox_import` into your Home Assistant `/config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Hoardo to Homebox Import**.
3. Enter the Homebox URL, username/email, and password.
4. Use the address Home Assistant can reach. For example, with the Homebox add-on this may be an internal add-on hostname and port.

The integration checks the credentials during setup. The password is stored in the Home Assistant config entry.

## Import from the UI

1. Open the **Hoardo to Homebox Import** integration card.
2. Select **Configure**.
3. Choose the Hoardo CSV file.
4. Enter the room name to use as the top-level Homebox location.
5. Submit the form. The import runs in the background and Home Assistant creates a persistent notification with the result.

## Import with a Home Assistant action

The integration registers the `hoardo_to_homebox_import.import_csv` action.

Example YAML:

```yaml
action: hoardo_to_homebox_import.import_csv
data:
  path: /config/hoardo/Family_Room_inventory.csv
  room: Family Room
```

The CSV must be stored in a path Home Assistant is allowed to read. By default, use a location under `/config`. If you configure more than one Homebox connection, also provide the `config_entry_id` field to select which connection to use.

## How data is organized

- The room value becomes a top-level Homebox location.
- Hoardo box names and box numbers become child locations, for example `Family Room / Holiday Decorations (#3)`.
- Each CSV item becomes a Homebox inventory entity inside its matching location.
- Category, Lists, and Notes are combined into the Homebox description.
- Photos are downloaded from their exported URLs and attached to the created item. The importer attempts to convert photos to JPEG when the required image support is available; otherwise it falls back to uploading the original AVIF.

## Re-import behavior

The integration stores completed item identifiers in Home Assistant storage. Re-running the same export for the same room skips rows already marked as imported. This prevents routine duplicate imports, but it is not a full two-way synchronization with Hoardo.

If an item was created in Homebox but its photo upload failed, review that item in Homebox before retrying. The importer currently records the item as complete before attaching its photo, so that row may be skipped on a later run.

## Troubleshooting

- **Cannot connect:** verify the Homebox URL from Home Assistant's network, including scheme and port.
- **Authentication failed:** verify the Homebox username/email and password.
- **404 or API errors:** confirm Homebox is version 0.26.0 or newer and that the account can access the entities API.
- **CSV cannot be read:** put it under `/config` or add its directory to Home Assistant's `allowlist_external_dirs`.
- **Photo download errors:** check that the photo URLs are still valid and reachable from Home Assistant.
- **Import results:** check the persistent notification and the Home Assistant log for the integration.

## Reporting issues

Please include your Home Assistant version, Homebox version, the relevant integration log lines, and a redacted example of the CSV headers. Never post your Homebox password, access token, or private photo URLs.

[Open an issue](https://github.com/kraroed/hoardo_to_homebox_import/issues)
