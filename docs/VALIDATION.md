# Validation record

Date: 2026-09-22.

## Executed

- Golden Subnet Map v0.2.0 test floor retained: 50 original test functions.
- Expanded Subnet Map 0.3.0 integration suite: **60/60 passed** on NetBox
  4.6.9/PostgreSQL using an isolated UTF-8 test database.
- Recovered VRF-aware validator suite: **27/27 passed** in the same isolated
  NetBox environment.
- Total application tests: **87/87 passed**.
- Native edit workflow changed status, DNS name and description through
  NetBox's own edit view and produced one user-attributed ObjectChange.
- Concurrent allocation produced one success and one authoritative 409 after
  PostgreSQL serialization/recheck; no silent race shortcut.
- Python compilation, YAML parsing, every shell script, Ansible playbook syntax,
  Subnet Map sdist/wheel build and wheel-content checks passed.
- Repository hygiene scan passed before commit; it is repeated in CI and after
  the fresh clone.

The disposable test database is removed after final validation. No live NetBox
database, LXC 9000, LXC 9001 or VM 140 data is reset or repurposed.

## Not executed

- Fresh RHEL 9.7 installation, reboot and second installer run: no disposable
  clean RHEL 9.7 x86_64 target was available. Existing RHEL/NetBox guests were
  not repurposed.
- Refreshed disconnected/offline bundle build and install.
- Live backup/restore on the new RHEL product image.
- Browser E2E on the new RHEL product image.

For those reasons this branch is `v1.0.0-rc1`, not a v1.0.0 production tag.
