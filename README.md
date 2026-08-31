# NetBox 4.6.9 Offline Deployment for RHEL 9.6

This repository builds and installs NetBox 4.6.9 natively on a pre-provisioned
RHEL 9.6 x86_64 VM. The target install is fully offline: RHEL RPMs, modular
metadata, the upstream NetBox source archive, and the complete Python 3.12
wheelhouse are carried in the bundle.

The office workflow is intentionally short:

```bash
tar -xzf NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
cd NETBOX-RHEL96-OFFLINE-1.0.0
vi config/site.yml
sudo python3 tools/initialize_secrets.py --output config/secrets.yml
sudo ./bootstrap.sh --preflight
sudo ./bootstrap.sh
```

Read `EDIT-ME-FIRST.md` before moving the bundle to a different VM. The company
distributable contains no populated secrets. `config/secrets.yml` is generated
privately on the target, is mode 0600, and is excluded from source control,
release manifests, ordinary database backups, and audit evidence. A separate
root-only private recovery checkpoint must never be sent through OPSWAT.

## Scope

- Native RHEL services: PostgreSQL 16, Redis 6.2, Gunicorn, NetBox RQ, nginx,
  firewalld, and systemd.
- SELinux remains Enforcing.
- Approved reusable taxonomy and device-type component templates are seeded.
- Fake operational inventory is not seeded.
- The read-only IPAM Audit Report is installed by default.
- Environment-specific validators and the write-capable allocation script are
  preserved but disabled by default.
- The former LXC/Proxmox deployment path is removed from the company installer.
- The separate topology/DCIM portal is deferred and is not deployed.

## Repository map

- `config/site.yml` — the one non-secret environment configuration file.
- `config/secrets.yml` — private deployment secrets; never commit it.
- `ansible/` — all system convergence logic.
- `data/bootstrap/` — human-readable foundation owned by bootstrap.
- `company/` — separately identifiable company extensions and operations tools.
- `acceptance/` — post-install platform and data-state validation.
- `artifacts/` — local RPM repositories, wheelhouse, and upstream source.
- `manifest/` — versions, inventory, and integrity checksums.
- `build/` — registered-RHEL bundle builder.

## Supported commands

```bash
sudo ./bootstrap.sh --preflight
sudo ./bootstrap.sh
sudo ./backup.sh
sudo ./restore.sh --archive /path/netbox-backup-YYYYMMDDTHHMMSSZ.tar.gz --confirm NETBOX-RESTORE
sudo /usr/local/sbin/netbox-acceptance
sudo /usr/local/sbin/netbox-release-audit
sudo /usr/local/sbin/netbox-restore-verify --archive /path/netbox-backup-YYYYMMDDTHHMMSSZ.tar.gz
```

See `docs/INSTALL-OFFLINE-RHEL96.md` for the detailed workflow and acceptance
criteria.
