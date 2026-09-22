#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo netbox-restore --archive /path/netbox-backup-*.tar.gz --confirm NETBOX-RESTORE" >&2
  exit 2
}

ARCHIVE=""
CONFIRM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ ${EUID} -eq 0 ]] || { echo "Restore must run as root." >&2; exit 1; }
[[ -f "${ARCHIVE}" && "${CONFIRM}" == "NETBOX-RESTORE" ]] || usage
[[ -f "${ARCHIVE}.sha256" ]] || { echo "Missing sidecar checksum." >&2; exit 1; }
(cd -- "$(dirname -- "${ARCHIVE}")" && sha256sum -c -- "$(basename -- "${ARCHIVE}.sha256")")

STAGING="$(mktemp -d --tmpdir netbox-restore.XXXXXXXX)"
trap 'rm -rf -- "${STAGING}"' EXIT
tar --acls --xattrs --selinux -C "${STAGING}" -xzf "${ARCHIVE}"
[[ -f "${STAGING}/database/netbox.dump" && -d "${STAGING}/files/etc/netbox" ]] || {
  echo "Archive lacks required database or configuration content." >&2
  exit 1
}

if [[ -f "${STAGING}/RESTORE-METADATA.txt" && -f /etc/netbox/deployment/secrets.yml ]]; then
  CURRENT_FINGERPRINTS="$(mktemp --tmpdir netbox-secret-fingerprints.XXXXXXXX)"
  /opt/netbox-company/bin/secret_fingerprints.py \
    --secrets /etc/netbox/deployment/secrets.yml > "${CURRENT_FINGERPRINTS}"
  if ! grep -E '^(django_secret_key_sha256|api_token_peppers_sha256|api_token_peppers_canonical_order)=' \
      "${STAGING}/RESTORE-METADATA.txt" | cmp -s - "${CURRENT_FINGERPRINTS}"; then
    echo "WARN: current secret-generation fingerprints do not match the backup; existing sessions or v2 API tokens may be affected." >&2
  fi
  rm -f -- "${CURRENT_FINGERPRINTS}"
fi

systemctl stop nginx netbox-rq netbox
runuser -u postgres -- dropdb --if-exists netbox
runuser -u postgres -- createdb --owner netbox netbox
runuser -u postgres -- pg_restore --exit-on-error --clean --if-exists --no-owner --role=netbox --dbname=netbox "${STAGING}/database/netbox.dump"
rsync -aHAX -- "${STAGING}/files/etc/netbox/" /etc/netbox/
if [[ -d "${STAGING}/files/etc/netbox-platform" ]]; then rsync -aHAX -- "${STAGING}/files/etc/netbox-platform/" /etc/netbox-platform/; fi
if [[ -d "${STAGING}/files/etc/pki/tls" ]]; then rsync -aHAX -- "${STAGING}/files/etc/pki/tls/" /etc/pki/tls/; fi
rsync -aHAX -- "${STAGING}/files/var/lib/netbox/media/" /var/lib/netbox/media/
rsync -aHAX -- "${STAGING}/files/opt/netbox-company/" /opt/netbox-company/
restorecon -RF /etc/netbox /etc/netbox-platform /etc/pki/tls/certs/netbox.crt /etc/pki/tls/private/netbox.key /var/lib/netbox /opt/netbox-company
systemctl start netbox netbox-rq nginx
/usr/local/sbin/netbox-verify
