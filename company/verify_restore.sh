#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo netbox-restore-verify --archive /path/netbox-backup-*.tar.gz" >&2
  exit 2
}

ARCHIVE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ ${EUID} -eq 0 ]] || { echo "Restore verification must run as root." >&2; exit 1; }
[[ -f "${ARCHIVE}" && -f "${ARCHIVE}.sha256" ]] || usage
(cd -- "$(dirname -- "${ARCHIVE}")" && sha256sum -c -- "$(basename -- "${ARCHIVE}.sha256")")

STAGING="$(mktemp -d --tmpdir netbox-restore-verify.XXXXXXXX)"
SCRATCH_DB="netbox_restore_verify_$$"
cleanup() {
  runuser -u postgres -- dropdb --if-exists "${SCRATCH_DB}" >/dev/null 2>&1 || true
  rm -rf -- "${STAGING}"
}
trap cleanup EXIT

tar --acls --xattrs --selinux -C "${STAGING}" -xzf "${ARCHIVE}"
[[ -f "${STAGING}/database/netbox.dump" ]] || { echo "[AUD-RST-001] FAIL — database dump missing"; exit 1; }
if tar -tzf "${ARCHIVE}" | grep -Eq '(^|/)(secrets\.yml|configuration\.py|.*private.*key.*)$'; then
  echo "[AUD-RST-002] FAIL — ordinary backup contains private configuration material"
  exit 1
fi

# The scratch restore runs under PostgreSQL's service account. Keep the
# extracted database private while granting that account the minimum traverse
# and read access required for pg_restore.
chown root:postgres "${STAGING}"
chmod 0710 "${STAGING}"
chown -R postgres:postgres "${STAGING}/database"
chmod 0700 "${STAGING}/database"
chmod 0600 "${STAGING}/database/netbox.dump"

runuser -u postgres -- createdb --owner=netbox "${SCRATCH_DB}"
runuser -u postgres -- pg_restore --exit-on-error --no-owner --role=netbox --dbname="${SCRATCH_DB}" "${STAGING}/database/netbox.dump"
MIGRATIONS="$(runuser -u postgres -- psql --dbname="${SCRATCH_DB}" --tuples-only --no-align --command='SELECT count(*) FROM django_migrations')"
DEVICES="$(runuser -u postgres -- psql --dbname="${SCRATCH_DB}" --tuples-only --no-align --command='SELECT count(*) FROM dcim_device')"
[[ "${MIGRATIONS}" =~ ^[1-9][0-9]*$ ]] || { echo "[AUD-RST-001] FAIL — restored migration history is invalid"; exit 1; }
[[ "${DEVICES}" == "0" ]] || { echo "[AUD-RST-001] FAIL — restored operational device count is not zero"; exit 1; }
echo "[AUD-RST-001] PASS — scratch database restore verified; operational_devices=0"
echo "[AUD-RST-002] PASS — ordinary backup excludes private configuration material"
