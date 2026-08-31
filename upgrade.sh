#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo ./upgrade.sh --bundle /approved/path/NETBOX-RHEL96-OFFLINE-<version>" >&2
  exit 2
}

[[ ${EUID} -eq 0 ]] || { echo "Upgrade must run as root (use sudo)." >&2; exit 1; }
[[ "${1:-}" == "--bundle" && -n "${2:-}" && $# -eq 2 ]] || usage
[[ -f /etc/netbox/.managed-by-netbox-rhel96-offline ]] || {
  echo "No managed NetBox RHEL96 installation marker was found." >&2
  exit 1
}

NEW_BUNDLE="$(realpath -e -- "$2")"
[[ -d "${NEW_BUNDLE}" ]] || usage
for required in bootstrap.sh backup.sh manifest/SHA256SUMS config/site.yml config/secrets.yml; do
  [[ -e "${NEW_BUNDLE}/${required}" ]] || {
    echo "New bundle is missing ${required}." >&2
    exit 1
  }
done

echo "Creating mandatory pre-upgrade backup..."
/usr/local/sbin/netbox-backup

echo "Running new bundle preflight..."
"${NEW_BUNDLE}/bootstrap.sh" --preflight

echo "Applying new offline bundle..."
"${NEW_BUNDLE}/bootstrap.sh"

echo "Running post-upgrade acceptance..."
/usr/local/sbin/netbox-acceptance
echo "Upgrade workflow completed successfully. Retain the pre-upgrade backup."
