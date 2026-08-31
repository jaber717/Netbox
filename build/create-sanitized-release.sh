#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: create-sanitized-release.sh --source-root /path/NETBOX-RHEL96-OFFLINE-1.0.0 --output-dir /secure/path" >&2
  exit 2
}

SOURCE_ROOT=""
OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root) SOURCE_ROOT="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -d "${SOURCE_ROOT}" && -d "${OUTPUT_DIR}" ]] || usage
SOURCE_ROOT="$(realpath -e -- "${SOURCE_ROOT}")"
OUTPUT_DIR="$(realpath -e -- "${OUTPUT_DIR}")"
export PYTHONDONTWRITEBYTECODE=1
PRODUCT="NETBOX-RHEL96-OFFLINE-1.0.0"
[[ "$(basename -- "${SOURCE_ROOT}")" == "${PRODUCT}" ]] || { echo "Unexpected source root name." >&2; exit 1; }
[[ -f "${SOURCE_ROOT}/config/secrets.yml" ]] || { echo "Private checkpoint source lacks config/secrets.yml." >&2; exit 1; }
[[ -f "${SOURCE_ROOT}/config/secrets.yml.example" ]] || { echo "Safe secrets example is missing." >&2; exit 1; }

ARCHIVE="${OUTPUT_DIR}/${PRODUCT}.tar.gz"
SIDECAR="${ARCHIVE}.sha256"
[[ ! -e "${ARCHIVE}" && ! -e "${SIDECAR}" ]] || { echo "Refusing to overwrite an existing release." >&2; exit 1; }

WORK_DIR="$(mktemp -d --tmpdir="${OUTPUT_DIR}" .sanitize.XXXXXXXX)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
STAGE="${WORK_DIR}/${PRODUCT}"
install -d -m 0755 "${STAGE}"
cp -a -- "${SOURCE_ROOT}/." "${STAGE}/"

SECRETS_TARGET="${STAGE}/config/secrets.yml"
[[ "${SECRETS_TARGET}" == "${STAGE}"/* ]] || { echo "Unsafe sanitization target." >&2; exit 1; }
rm -f -- "${SECRETS_TARGET}"

chmod 0755 \
  "${STAGE}/bootstrap.sh" "${STAGE}/backup.sh" "${STAGE}/restore.sh" \
  "${STAGE}/upgrade.sh" "${STAGE}/build/create-sanitized-release.sh" \
  "${STAGE}/tools/generate_manifest.py" "${STAGE}/tools/initialize_secrets.py" \
  "${STAGE}/tools/preflight.py" "${STAGE}/tools/secret_audit.py" \
  "${STAGE}/tools/verify_edit_me_first.py" "${STAGE}/company/backup.sh" \
  "${STAGE}/company/restore.sh" "${STAGE}/company/verify_restore.sh" \
  "${STAGE}/company/secret_fingerprints.py" "${STAGE}/acceptance/acceptance.py" \
  "${STAGE}/acceptance/release_audit.py"

python3 "${STAGE}/tools/generate_manifest.py" --root "${STAGE}"
python3 "${STAGE}/tools/secret_audit.py" --root "${STAGE}" --classification distributable \
  --private-values-from "${SOURCE_ROOT}/config/secrets.yml" \
  > "${STAGE}/manifest/SANITIZATION-AUDIT.txt"
python3 "${STAGE}/tools/verify_edit_me_first.py" \
  --config "${STAGE}/config/site.yml" --document "${STAGE}/EDIT-ME-FIRST.md" \
  > "${STAGE}/manifest/EDIT-ME-FIRST-AUDIT.txt"
python3 "${STAGE}/tools/generate_manifest.py" --root "${STAGE}"
python3 "${STAGE}/tools/secret_audit.py" --root "${STAGE}" --classification distributable \
  --private-values-from "${SOURCE_ROOT}/config/secrets.yml" >/dev/null

GENERATED_RUNTIME_ENTRY="$(find "${STAGE}" \
  \( -type d -name __pycache__ -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
  -print -quit)"
[[ -z "${GENERATED_RUNTIME_ENTRY}" ]] || {
  echo "Generated runtime entry is forbidden in the distributable: ${GENERATED_RUNTIME_ENTRY}" >&2
  exit 1
}

SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-0}"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner \
  -C "${WORK_DIR}" -cf - "${PRODUCT}" | gzip -n -9 > "${ARCHIVE}"
(cd -- "${OUTPUT_DIR}" && sha256sum "$(basename -- "${ARCHIVE}")" > "$(basename -- "${SIDECAR}")")
chmod 0644 "${ARCHIVE}" "${SIDECAR}"
echo "SANITIZED RELEASE COMPLETE"
stat -c 'bytes=%s path=%n' "${ARCHIVE}"
sha256sum "${ARCHIVE}"
