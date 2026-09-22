# Architecture

The repository is the complete deployment input. `install.sh` prepares local
configuration/secrets and invokes one Ansible convergence graph for connected
or offline package sources.

```text
RHEL 9.x
  nginx/TLS/firewalld/SELinux
    Gunicorn → NetBox 4.6.9 → PostgreSQL 16
             ↘ NetBox RQ → Redis
             ↘ vendored Subnet Map → native NetBox IPAM models/forms
```

The product adds no database. Subnet Map reads native NetBox objects using
permission-restricted querysets. Writes use `IPAddressForm`, CSRF, permissions,
validation, changelog events, a PostgreSQL advisory transaction lock, and a
final authoritative occupancy recheck.

Persistent state is PostgreSQL, media, root-only deployment configuration, TLS
material and `/etc/netbox-platform/release.json`. Upstream source lives in a
pinned release directory with `/opt/netbox` as the stable symlink. Product
extensions remain separate from NetBox core.

`install.sh` is idempotent for a valid managed release. Unknown installations
are conflicts. Foundation seeding converges declared native objects and never
deletes inventory.
