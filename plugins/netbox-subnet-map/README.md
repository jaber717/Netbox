# NetBox Subnet Map

A native NetBox plugin that provides an interactive per-prefix address map and grid-driven IP allocation while preserving NetBox as the source of truth.

## Features

- Native Prefix Subnet Map tab, IPv4 grid, /23 and /22 block visualization, and large-prefix table mode.
- Real IPAddress overlays, duplicate IP object support, IPRange and child Prefix overlays.
- Interface, VMInterface, FHRP assignment visibility and interface MAC visibility.
- Permission-aware fail-closed availability, NetBox Available, and Operationally Unclaimed metrics.
- Native Quick Add allocation with NetBox validation and changelog attribution.
- No discovery, scanning, or second source of truth.

## Screenshots

Screenshots are intentionally omitted until generic, non-deployment-specific examples are available.

## Requirements

Tested baseline: **NetBox 4.6.9**. Other versions have not been tested.

## Installation

Install the package in NetBox's Python environment, add `netbox_subnet_map` to `PLUGINS`, run `collectstatic`, and restart services using the deployment's normal procedure. No plugin models or migrations are required.

## Configuration

Use optional `PLUGINS_CONFIG['netbox_subnet_map']` settings.

| Setting | Default | Hard bounds |
| --- | ---: | --- |
| `host_grid_limit` | 1024 | 1–1024 |
| `related_object_limit` | 2000 | 1–10000 |
| `hosts_per_page` | 128 | 1–1000 |

## Usage

Open **IPAM → Prefixes → select a Prefix → Subnet Map**. Select a cell to inspect it, then use **Allocate IP** for an eligible available address to open NetBox's native Quick Add workflow.

## Permissions

The plugin fails closed when it cannot safely determine occupancy. See [permissions](docs/permissions.md).

## Architecture

See [architecture](docs/architecture.md).

## Limitations

- Tested only on NetBox 4.6.9.
- Allocation is limited to complete visible IPv4 grids within the configured ceiling.
- Editing existing IP objects, search/filtering, network discovery, and MAC creation are not implemented.

## Development

Run integration tests in an isolated NetBox environment. This repository deliberately contains no deployment-specific test configuration.

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
