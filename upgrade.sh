#!/usr/bin/env bash
set -euo pipefail

usage() { echo "Usage: sudo ./upgrade.sh --target-version <pinned-version>" >&2; exit 2; }
[[ ${EUID} -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ "${1:-}" == "--target-version" && -n "${2:-}" && $# -eq 2 ]] || usage
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="$2"
[[ -f /etc/netbox/.managed-by-netbox-platform && -f /etc/netbox-platform/release.json ]] || {
  echo "No managed NetBox Platform installation was found." >&2; exit 1;
}
cd "${ROOT_DIR}"
PINNED="$(python3 -c 'import sys; sys.path.insert(0,"tools"); from site_config import load_and_validate; print(load_and_validate("config/site.yml")["netbox"]["version"])')"
[[ "${TARGET}" == "${PINNED}" ]] || {
  echo "Target ${TARGET} is not the reviewed version pinned by this checkout (${PINNED})." >&2; exit 1;
}
grep -q "${TARGET}" plugins/netbox-subnet-map/COMPATIBILITY.md || {
  echo "Subnet Map does not declare compatibility with NetBox ${TARGET}." >&2; exit 1;
}
pg_isready -q || { echo "PostgreSQL health check failed." >&2; exit 1; }
/usr/local/sbin/netbox-verify
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py showmigrations --plan >/dev/null
echo "Creating mandatory pre-upgrade backup..."
/usr/local/sbin/netbox-backup
./install.sh --preflight
./install.sh
/usr/local/sbin/netbox-verify
echo "Upgrade/convergence to reviewed NetBox ${TARGET} completed. Retain the pre-upgrade backup."
