# EDIT ME FIRST — Office Deployment Checklist

This bundle currently contains a **HOME LAB EXAMPLE**. Before running it on the
company DEV VM, collect the values below from the system team and edit
`config/site.yml`. Do not invent network values. The installer validates the
network but never changes the NIC, address, routes, DNS, or NTP.

## Values to obtain

- VM hostname and FQDN
- interface name
- IPv4 address and prefix length
- default gateway
- DNS server addresses
- NTP server addresses and synchronization policy
- allowed DNS names/IPs for NetBox
- TLS certificate, private key, and CA-chain paths, or approval for temporary
  self-signed DEV TLS
- approved backup path and any future off-box destination
- package source mode: `bundle` or explicitly approved `satellite`

## Settings table

| Setting | File | Current home-lab example | Change when | Behavior |
|---|---|---|---|---|
| Environment label | `config/site.yml` | `home-lab-dev` | Company DEV naming is known | Configures metadata |
| Hostname | `config/site.yml` | `netbox-dev` | Company hostname differs | Validates only |
| FQDN | `config/site.yml` | `netbox-dev` | Company FQDN is known | Configures nginx/NetBox and validates DNS |
| Interface | `config/site.yml` | `ens18` | Company NIC differs | Validates only |
| IP/CIDR | `config/site.yml` | `192.168.1.91/24` | Always for company VM | Validates only |
| Gateway | `config/site.yml` | `192.168.1.1` | Always for company VM | Validates only |
| DNS | `config/site.yml` | `192.168.1.1` | Always for company VM | Validates only |
| NTP | `config/site.yml` | `192.168.1.1` | Always for company VM | Validates only |
| Allowed hosts/origins | `config/site.yml` | Home DNS/IP | Hostname/FQDN/IP change | Configures NetBox security |
| TLS mode | `config/site.yml` | `self_signed_dev` | Company certificate is supplied | Configures nginx |
| Certificate/key/CA | `config/site.yml` | `/etc/pki/tls/...` | `tls.mode: supplied` | Validates and configures nginx |
| Admin username | `config/site.yml` | `admin` | Normally keep | Configures initial admin |
| Admin password | `config/secrets.yml` | `SECRET` | Rotate for another environment | Secret; configures admin |
| Package source | `config/site.yml` | `bundle` | Approved Satellite is required | Configures DNF source; never auto-switches |
| Backup path | `config/site.yml` | `/var/backups/netbox` | Company storage differs | Configures backup |
| Validators | `config/site.yml` | disabled | Policy is formally approved | Optional feature |
| Allocation request | `config/site.yml` | disabled | Write policy is formally approved | Optional write feature |

## Complete `config/site.yml` schema coverage

The following machine-checked list is the complete field-by-field schema. Every
key exists in the supplied file. Review the environment-specific values even
when the fixed software-version and feature-default keys do not need editing.

<!-- CONFIG-SCHEMA-KEYS-BEGIN -->
- `deployment.environment`
- `deployment.bundle_version`
- `server.hostname`
- `server.fqdn`
- `server.timezone`
- `expected_network.interface`
- `expected_network.ip_address`
- `expected_network.cidr`
- `expected_network.gateway`
- `expected_network.dns`
- `expected_network.ntp`
- `expected_network.require_ntp_synchronized`
- `packages.source`
- `netbox.version`
- `netbox.admin_username`
- `netbox.allowed_hosts`
- `netbox.csrf_trusted_origins`
- `postgresql.version`
- `postgresql.database`
- `postgresql.username`
- `redis.version`
- `redis.bind`
- `nginx.stream`
- `nginx.redirect_http_to_https`
- `tls.mode`
- `tls.certificate`
- `tls.private_key`
- `tls.ca_chain`
- `backup.local_path`
- `backup.retention_days`
- `backup.offbox_target`
- `features.bootstrap_taxonomy`
- `features.environment_validators`
- `features.ipam_audit_report`
- `features.ipam_allocation_request`
<!-- CONFIG-SCHEMA-KEYS-END -->

## COMPANY DEV EXAMPLE

Use placeholders until the system team provides authoritative values:

```yaml
server:
  hostname: <COMPANY_HOSTNAME>
  fqdn: <COMPANY_FQDN>
  timezone: Asia/Riyadh

expected_network:
  interface: <COMPANY_INTERFACE>
  ip_address: <COMPANY_VM_IP>
  cidr: <COMPANY_VM_IP>/<PREFIX>
  gateway: <COMPANY_GATEWAY>
  dns:
    - <COMPANY_DNS_1>
    - <COMPANY_DNS_2>
  ntp:
    - <COMPANY_NTP_1>
  require_ntp_synchronized: true

netbox:
  allowed_hosts:
    - <COMPANY_FQDN>
    - <COMPANY_VM_IP>
  csrf_trusted_origins:
    - https://<COMPANY_FQDN>

tls:
  mode: supplied
  certificate: <APPROVED_CERTIFICATE_PATH>
  private_key: <APPROVED_PRIVATE_KEY_PATH>
  ca_chain: <APPROVED_CA_CHAIN_PATH>
```

Also review `data/bootstrap/organization.yml`. The preserved tenants, regions,
sites, and locations are explicitly marked as home-lab organizational examples.
Rename or remove them before company deployment if they are not intended state.

## Commands to run

```bash
sha256sum -c NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256
tar -xzf NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
cd NETBOX-RHEL96-OFFLINE-1.0.0
# The distributable contains no populated secrets. This prompts for the initial
# admin password and generates all other values locally without printing them.
sudo python3 tools/initialize_secrets.py --output config/secrets.yml
sudo ./bootstrap.sh --preflight
sudo ./bootstrap.sh
```

Do not continue after a preflight `FAIL`. Correct the declared value or have the
system team correct the VM; the installer deliberately makes no networking
changes.
