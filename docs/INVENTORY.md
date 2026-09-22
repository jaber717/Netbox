# Implementation inventory

Inventory date: 2026-09-22. Runtime inspection was read-only.

| Area | Classification | Evidence |
| --- | --- | --- |
| Primary GitHub repository | Implemented, offline-tested historically | `jaber717/Netbox`, baseline `214dc20`; compact source history and legacy RHEL 9.6 offline product |
| NetBox | Implemented + tested in lab | 4.6.9 on both LXC 9000 and 9001 |
| Subnet Map v0.2.0 | Implemented + tested | Golden repository/tag at commit `d401311c3789bdedb93e1251d9f98cd011d87f3a`; 50 tests |
| Broader IPAM validators | Implemented + previously uncommitted | Exactly 27 isolated VRF policy tests located in the current lab filesystem; preserved for review, disabled by default |
| Connected RHEL installer | Implemented + source-tested | New `install.sh` and shared Ansible roles; clean RHEL 9.7 E2E remains required |
| Backup/restore | Implemented, productionized | Guarded restore confirmation, PostgreSQL custom dump, media/config/TLS, scratch restore verifier |
| Upgrade | Implemented, target-pinned | Compatibility check, health/verify, mandatory backup, converge, post-verify |
| CMDB | Partial | Runtime fields/choices/validator/report exist on 9001; no dedicated tests or relationships located |
| Offline mode | Legacy/secondary | Builder retained; not the golden path and not revalidated in this release |

## Inspected runtime

The virtualization host was Debian 12 / Proxmox 8.4.13 on x86_64. LXC 9000
and 9001 were both Ubuntu 24.04 x86_64 with Python 3.12.3, PostgreSQL 16.15,
Redis 7.0.15 and nginx 1.24.0. The production target remains RHEL 9.x x86_64;
these Ubuntu guests are evidence/test environments, not release E2E proof.

LXC 9000 loaded Reorder Rack and Subnet Map 0.2.0, plus two custom IPAM
validators. LXC 9001 loaded `inventory_monitor`, the CMDB validator, and the
CMDB objects documented in [CMDB audit](CMDB-AUDIT.md). Neither guest was
destroyed, reset, or repurposed.

## Golden-source decisions

- The Subnet Map source is vendored under `plugins/netbox-subnet-map`.
- Provenance: `jaber717/netbox-subnet-map`, v0.2.0,
  `d401311c3789bdedb93e1251d9f98cd011d87f3a`.
- NetBox remains the only IPAM/asset database.
- No third-party inventory/lifecycle plugin was added.
- CMDB prototypes are preserved but are not enabled by Production v1.
