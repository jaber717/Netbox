# Offline Installation on RHEL 9.6

## Prerequisites

The target must be a pre-provisioned RHEL 9.6 x86_64 VM with working hostname,
addressing, gateway, DNS, and time synchronization. Use an account with
passwordless or interactive sudo. Root SSH is neither required nor recommended.
SELinux must be Enforcing.

The bundle supports explicit package modes:

- `bundle` (default): every required RPM is installed from the embedded local
  repositories. External repositories are disabled for package convergence.
- `satellite`: OS RPMs may come from approved configured repositories. NetBox,
  Python wheels, and company artifacts remain local. There is no automatic
  fallback between modes.

## Transfer and integrity

After OPSWAT approval, copy the archive and checksum sidecar from the approved
internal staging area. Do not mount or pass the USB directly to the VM.

```bash
sha256sum -c NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256
tar -xzf NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
cd NETBOX-RHEL96-OFFLINE-1.0.0
```

The archive itself contains `manifest/SHA256SUMS`. `bootstrap.sh` verifies that
manifest before installation. `config/site.yml` is intentionally excluded from
the inner integrity manifest because it is the documented non-secret environment
input. The distributable has no populated `config/secrets.yml`.

## Configure

Read `EDIT-ME-FIRST.md`. Edit only `config/site.yml` for non-secret environment
values. Generate `config/secrets.yml` on the target without printing values:

```bash
sudo python3 tools/initialize_secrets.py --output config/secrets.yml
```

The generated file is mode 0600. Preserve its values in company-approved
secret/password management separate from the release and database backup. Do
not regenerate it on a rerun. Losing matching `API_TOKEN_PEPPERS` affects
existing v2 API-token verification; changing `SECRET_KEY` invalidates existing
user sessions but does not destroy stored NetBox data.

## Preflight and install

```bash
sudo ./bootstrap.sh --preflight
sudo ./bootstrap.sh
```

Preflight is read-only. It validates exact OS/minor/architecture, resources,
SELinux, declared networking, DNS, NTP, listeners, prior installations, local
repository metadata, wheelhouse completeness, source presence, TLS inputs,
integrity, and secret-file structure. Any critical failure stops installation.

Bootstrap installs Ansible from the selected package source if needed, then
runs the local playbook. All application convergence is in Ansible roles.

## Expected state

Externally reachable services are HTTPS 443 and optional HTTP 80 redirect.
PostgreSQL 5432, Redis 6379, and Gunicorn 8001 bind to loopback only. SSH remains
owned by the system team.

The approved foundation is present, including manufacturers, roles, platforms,
device types and component templates, tenancy/site/location examples, IPAM
roles/RIR, circuit taxonomy, and the criticality custom field. Operational
inventory remains empty: no racks, devices, prefixes, IPs, VLANs, cables,
aggregates, circuits, or terminations.

## Re-run

Run the same command again:

```bash
sudo ./bootstrap.sh
```

A successful rerun must not rotate secrets, recreate the database, duplicate
foundation objects, or change operational inventory. Acceptance includes an
independent taxonomy second pass requiring `created=0 updated=0`.

## Post-install commands

```bash
sudo /usr/local/sbin/netbox-acceptance
sudo /usr/local/sbin/netbox-release-audit
sudo ./backup.sh
systemctl status netbox netbox-rq nginx postgresql redis
```

Browse to `https://<configured-fqdn>` and sign in with the configured initial
administrator. Replace self-signed DEV TLS before production use.
