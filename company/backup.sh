#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Backup must run as root." >&2
  exit 1
fi

BACKUP_ROOT="${NETBOX_BACKUP_ROOT:-/var/backups/netbox}"
RETENTION_DAYS="${NETBOX_BACKUP_RETENTION_DAYS:-14}"
OFFBOX_TARGET="${NETBOX_BACKUP_OFFBOX_TARGET:-}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${BACKUP_ROOT}/netbox-backup-${TIMESTAMP}.tar.gz"
STAGING="$(mktemp -d --tmpdir netbox-backup.XXXXXXXX)"
trap 'rm -rf -- "${STAGING}"' EXIT

BACKUP_ROOT="$(realpath -m -- "${BACKUP_ROOT}")"
case "${BACKUP_ROOT}" in
  /|/var|/var/backups|/home|/root) echo "Unsafe backup root: ${BACKUP_ROOT}" >&2; exit 1 ;;
esac

install -d -m 0700 -o root -g root "${BACKUP_ROOT}" "${STAGING}/database" "${STAGING}/files"
runuser -u postgres -- pg_dump --format=custom netbox > "${STAGING}/database/netbox.dump"
runuser -u postgres -- pg_dumpall --globals-only > "${STAGING}/database/globals.sql"

# Database backup and private-secret recovery are separate security artifacts.
# Deliberately exclude /etc/netbox/configuration.py and deployment/secrets.yml.
for source in \
  /etc/netbox/gunicorn.py \
  /etc/netbox/.managed-by-netbox-rhel96-offline \
  /etc/netbox/deployment/site.yml \
  /var/lib/netbox/media \
  /opt/netbox-company \
  /etc/nginx/conf.d/netbox.conf \
  /etc/systemd/system/netbox.service \
  /etc/systemd/system/netbox-rq.service; do
  if [[ -e "${source}" ]]; then
    rsync -aR -- "${source}" "${STAGING}/files/"
  fi
done

cat > "${STAGING}/RESTORE-METADATA.txt" <<EOF
created_utc=${TIMESTAMP}
hostname=$(hostname -f 2>/dev/null || hostname)
netbox_version=$(/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c 'from django.conf import settings; print(settings.VERSION)' 2>/dev/null | tail -n 1)
database=netbox
secret_recovery=external_company_secret_management_required
EOF
/opt/netbox-company/bin/secret_fingerprints.py \
  --secrets /etc/netbox/deployment/secrets.yml >> "${STAGING}/RESTORE-METADATA.txt"

tar --numeric-owner --acls --xattrs --selinux -C "${STAGING}" -czf "${ARCHIVE}" .
chmod 0600 "${ARCHIVE}"
sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"
chmod 0600 "${ARCHIVE}.sha256"

find "${BACKUP_ROOT}" -maxdepth 1 -type f -name 'netbox-backup-*.tar.gz*' -mtime "+${RETENTION_DAYS}" -delete

if [[ -n "${OFFBOX_TARGET}" ]]; then
  rsync -a --protect-args -- "${ARCHIVE}" "${ARCHIVE}.sha256" "${OFFBOX_TARGET}/"
fi

echo "Backup created: ${ARCHIVE}"
