# Architecture

## Runtime

```text
Client HTTPS
    |
    v
nginx :443 (:80 optional redirect)
    |
    v
Gunicorn 127.0.0.1:8001 -> NetBox 4.6.9 / Python 3.12 venv
                              |                 |
                              v                 v
                    PostgreSQL 16        Redis 6.2 / NetBox RQ
                    127.0.0.1:5432       127.0.0.1:6379
```

Systemd owns `netbox.service`, `netbox-rq.service`, nginx, PostgreSQL, Redis,
firewalld, and the backup timer. There is no container runtime and no legacy
NetBox housekeeping timer.

## Filesystem separation

- `/opt/netbox-4.6.9` — pinned upstream source and Python venv.
- `/opt/netbox` — stable symlink to the active release.
- `/opt/netbox-company` — bootstrap and company extensions.
- `/etc/netbox` — private runtime configuration and disaster-recovery inputs.
- `/var/lib/netbox` — media and custom scripts.
- `/var/www/netbox/static` — collected static files, linked from NetBox's fixed
  release static root.
- `/var/backups/netbox` — private local backups.

## Deployment control plane

`bootstrap.sh` is a thin entrypoint: it checks privileges, runs immutable
preflight, makes local Ansible available, and invokes `ansible/site.yml`.
Ansible roles own package repositories, RPMs, PostgreSQL, Redis, NetBox,
extensions, nginx/TLS, SELinux, firewalld, taxonomy, backup, and acceptance.

In bundle mode DNF uses two embedded repositories with external repositories
disabled. The modular repository preserves modulemd for PostgreSQL 16 and nginx
1.24. Python uses `pip --no-index --find-links` against the embedded wheelhouse.

## Data ownership

Bootstrap owns only declared foundation objects in `data/bootstrap`. The
converger validates each new/changed object with NetBox model validation before
saving. It never creates operational inventory. After go-live, NetBox is the
source of truth for real devices, addresses, prefixes, VLANs, cables, circuits,
and other operational records; there is no continuous Git reconciliation over
that inventory.

## Security

- SELinux remains Enforcing; standard booleans and file contexts are used.
- nginx may connect only as allowed by the standard HTTPD boolean.
- PostgreSQL, Redis, and Gunicorn are loopback-only.
- Firewalld opens only the configured web ports and explicitly removes public
  rules for internal service ports.
- Generated configuration and secrets are root-owned with restricted group/read
  access required by the NetBox and nginx service accounts.
- Passwords and cryptographic values are passed through private files or hidden
  environment variables and are suppressed from Ansible logs.

## Port classification from the old project

- **KEEP AS-IS:** reusable taxonomy intent, device type/component definitions,
  safe company report/validator source, NetBox/Gunicorn/systemd principles.
- **KEEP BUT MODIFY:** Ubuntu packages/paths, Redis path, SELinux/firewall,
  static storage, data seeding, secret handling, acceptance, and backup.
- **REMOVE:** LXC lifecycle, `pct` operations, Ubuntu apt assumptions, demo
  operational inventory, and legacy housekeeping automation.
- **DEFER:** topology/DCIM/IPAM portal and write-capable allocation workflow.
