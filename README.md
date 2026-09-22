# NetBox Platform

Production-oriented NetBox 4.6.9 for connected RHEL 9.x x86_64, with the
native Subnet Map/IPAM product, guarded allocation, verification, backup,
restore and target-pinned upgrades. Release state: **v1.0.0-rc1** pending a
clean RHEL 9.7 end-to-end installation and second-run convergence test.

## Install

On a fresh registered RHEL 9.x x86_64 host with working enabled repositories:

```bash
sudo dnf install -y git
git clone https://github.com/jaber717/Netbox.git
cd Netbox
git checkout codex/production-connected
sudo ./install.sh
sudo ./verify.sh
```

The installer prompts once for the initial admin password; all other secrets
are generated locally with mode 0600 and are never printed. It detects:

- `FRESH`: installs the complete platform.
- `MANAGED-CONVERGE`: safely reruns against a valid managed release state.
- `CONFLICT`: refuses an unknown installation or occupied service ports.

Run a read-only preflight with `sudo ./install.sh --preflight`. The primary
target is RHEL 9.7; validation accepts `ID=rhel`, any `VERSION_ID=9.x`, and
`x86_64`. RHEL 8/10, other distributions and other architectures are rejected.

For this private repository, authenticate with GitHub CLI (`gh auth login` then
`gh repo clone jaber717/Netbox`) or an SSH key (`git clone
git@github.com:jaber717/Netbox.git`). Do not embed tokens in clone URLs or
installer configuration.

## Product scope

- NetBox 4.6.9, pinned to a verified upstream source SHA-256.
- PostgreSQL 16, Redis, Gunicorn, NetBox RQ, nginx, systemd.
- SELinux Enforcing and firewalld enabled.
- PostgreSQL, Redis and Gunicorn bound to loopback.
- Vendored Subnet Map 0.3.0, automatically installed and configured.
- Optional generic taxonomy convergence; no real company inventory.
- Daily root-only backup, guarded restore, scratch restore verification.
- `/etc/netbox-platform/release.json` managed release metadata.

The installer does not alter NIC, routing, DNS, NTP, Red Hat subscription
ownership, or repository enrollment. If DNF is unavailable or unregistered it
stops with a preflight error.

## Subnet Map/IPAM

The approved architecture comes from `jaber717/netbox-subnet-map` v0.2.0 at
commit `d401311c3789bdedb93e1251d9f98cd011d87f3a`. Its source is vendored under
`plugins/netbox-subnet-map`; installation never needs a second clone or manual
wheel build.

The product preserves its IPv4 grid, /23 and /22 views, large/IPv6 table mode,
IPRange/child-prefix overlays, duplicate IP objects, interfaces, VM interfaces,
FHRP, MAC context, fail-closed permissions, metrics and native Quick Add. The
0.3.0 work adds:

- server-side search/filtering for address/CIDR, Prefix, VRF, tenant, status,
  device, interface, VM, DNS, VLAN and site;
- native NetBox IPAddress editing from the Inspector;
- next-IP, free-range and requested child-prefix discovery;
- VRF-scoped conflict simulation;
- PostgreSQL allocation serialization and authoritative in-transaction recheck.

NetBox is the only source of truth. There is no scanner, shadow IP database, or
separate asset store. Active network discovery and MAC creation remain outside
v1 scope.

## Configuration

`install.sh` creates ignored `config/site.yml` from
`config/site.yml.example` using current host facts. Review the file when DNS,
TLS or backup policy differs. Secrets live only in ignored
`config/secrets.yml` and the managed host's root-only deployment directory.

Generic foundation data is under `data/foundation`. The historical lab/company
example is isolated under `data/examples/company-lab` and is never seeded.
Normal convergence uses update-or-create behavior and never deletes inventory.

The legacy environment ownership validators are disabled by default. They are
policy-specific and must not be enabled until their tenant/supernet model is
approved. CMDB cannot be enabled in this release; see
[CMDB audit](docs/CMDB-AUDIT.md).

## Operations

```bash
sudo ./verify.sh
sudo ./backup.sh
sudo ./restore.sh --archive /path/netbox-backup-YYYYMMDDTHHMMSSZ.tar.gz --confirm NETBOX-RESTORE
sudo ./upgrade.sh --target-version 4.6.9
```

`verify.sh` checks services, migrations, static assets, HTTPS/API/login,
plugin loading and route registration, release state, SELinux, firewalld and
loopback-only internal services. Restore is never automatic and requires the
exact confirmation token. Upgrade accepts only the version pinned by the
checked-out release, validates Subnet Map compatibility, verifies current
health, creates a mandatory backup, converges and verifies again.

Backups include PostgreSQL, media, non-secret site configuration, managed
service configuration, release state, and the locally managed TLS certificate
and key. Django/database/API secrets remain a separate recovery artifact.
Backups are mode 0600 and are never stored in Git.

## Offline mode

Connected installation is the golden path. The prior bundle builder remains in
`build/` as a secondary capability and shares the same Ansible roles, but this
RC does not claim a refreshed offline bundle validation. Large RPM repositories,
wheel caches and archives are excluded from Git and belong in release artifacts.

## Development and CI

CI performs Python compilation, YAML parsing, shell syntax, repository/history
hygiene, plugin packaging, and the complete Subnet Map integration suite against
NetBox 4.6.9 with PostgreSQL 16. Tests refuse to use a non-test database.

See [inventory](docs/INVENTORY.md), [architecture](docs/ARCHITECTURE.md),
[backup/restore](docs/BACKUP-RESTORE.md), [upgrade](docs/UPGRADE.md), and
[troubleshooting](docs/TROUBLESHOOTING.md).

## Security and limitations

TLS and RPM GPG verification are not disabled. NetBox permissions, CSRF,
forms/validation and changelog behavior remain authoritative. The repository
must pass `python3 tools/repository_hygiene.py` before release.

Known release limitations:

- Clean RHEL 9.7 install, reboot and second-run convergence are not yet executed.
- CMDB is `PARTIAL` and excluded from production.
- The refreshed offline bundle is not validated by this RC.
