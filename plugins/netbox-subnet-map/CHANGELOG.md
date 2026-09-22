# Changelog

## 0.3.0

- Add permission-trimmed search/filtering and native IP edit actions.
- Add VRF-aware free-space discovery and conflict simulation.
- Serialize allocation attempts and recheck authoritative state in-transaction.
- Preserve the v0.2.0 architecture and all original tests.

## 0.2.0

### Added
- Native Prefix Subnet Map with Grid, Table, Inspector, IPRange and child-prefix context, duplicate address representation, permission-aware availability, structured allocation state, native Quick Add allocation, and native changelog attribution.

### Changed
- Numeric pagination, normalized range/child payloads, bounded grid rendering, and separated availability metrics.

### Security
- Fail-closed hidden occupancy handling, server-side allocation recheck, and native CSRF, permission, and validation enforcement.
