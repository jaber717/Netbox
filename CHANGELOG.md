# Changelog

## 1.0.0-rc1 — connected production candidate

- Make connected RHEL 9.x x86_64 the primary install path.
- Vendor and automatically install Subnet Map from the approved v0.2.0 base.
- Add Subnet Map 0.3.0 search, native edit, free-space/conflict and serialized allocation workflows.
- Add `install.sh`, `verify.sh`, managed release state and target-pinned upgrade.
- Separate generic foundation from historical lab examples.
- Classify and preserve CMDB as partial without enabling it in production.
- Add platform CI and Git-history hygiene scanning.

## 1.0.0 final release audit

- Split the root-only private recovery checkpoint from the sanitized OPSWAT
  distributable; only the sanitized artifact is eligible for release testing.
- Persisted the offline RPM repositories under `/opt/netbox-offline-repo/1.0.0`.
- Added stable-ID release audit evidence, API zero-inventory checks, dynamic
  acceptance totals, and isolated scratch-database restore proof.
- Separated ordinary database/configuration backups from private secret
  recovery and added canonical non-secret generation fingerprints.
- Added machine verification of `EDIT-ME-FIRST.md` against all `site.yml` keys.
- Import the RHEL package-signing key from the clean target before the initial
  offline `ansible-core` installation, preserving signature verification
  without requiring Internet or subscription repository access.
- Grant PostgreSQL's service account narrowly scoped access to the extracted
  scratch dump so the isolated restore proof succeeds without relaxing backup
  archive permissions.
- Authenticate zero-inventory API evidence with an ephemeral read-only local
  audit token that is deleted immediately and never enters logs or evidence.
- Suppress Python bytecode during release assembly and fail packaging if any
  generated `__pycache__`, `.pyc`, or `.pyo` entry remains.
- Preserve the base and modular RPM repositories independently with `cp -aT`,
  preventing source-directory metadata from changing the managed persistent
  repository parent on the second bootstrap.

## 1.0.0 — 2026-08-31

- Ported the existing NetBox engineering foundation from Ubuntu/LXC assumptions
  to native RHEL 9.6 x86_64.
- Pinned NetBox 4.6.9, Python 3.12.9, PostgreSQL 16.10, Redis 6.2.20,
  nginx 1.24.0, and Ansible Core 2.14.18.
- Added complete offline RHEL repositories with preserved PostgreSQL/nginx
  module metadata and a fully rehearsed Python wheelhouse.
- Added strict read-only environment preflight and package-source modes.
- Added native systemd, nginx/TLS, SELinux Enforcing, and firewalld convergence.
- Extracted approved reusable manufacturers, roles, platforms, device types,
  component templates, organizational structure, schema, IPAM roles, and circuit
  taxonomy from the read-only reference system.
- Removed all fake operational inventory from bootstrap ownership.
- Preserved company validator/report code with risky/write-capable features
  disabled by default.
- Added backup, guarded restore, acceptance, idempotency, transfer integrity,
  and future offline-upgrade workflow.
- Deferred the separate topology/DCIM/IPAM portal.
