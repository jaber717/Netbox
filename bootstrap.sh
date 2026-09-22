#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MODE="install"
if [[ "${1:-}" == "--preflight" ]]; then
  MODE="preflight"
elif [[ $# -gt 0 ]]; then
  echo "Usage: sudo ./bootstrap.sh [--preflight]" >&2
  exit 2
fi

if [[ ${EUID} -ne 0 ]]; then
  echo "FAIL: bootstrap must run as root (use sudo)." >&2
  exit 1
fi

cd "${ROOT_DIR}"
if [[ "${MODE}" == "preflight" ]]; then
  python3 tools/preflight.py --root "${ROOT_DIR}" --allow-missing-secrets
else
  python3 tools/preflight.py --root "${ROOT_DIR}"
fi
if [[ "${MODE}" == "preflight" ]]; then
  exit 0
fi

if ! command -v ansible-playbook >/dev/null 2>&1; then
  PACKAGE_SOURCE="$(python3 -c 'import sys; sys.path.insert(0,"tools"); from site_config import load_and_validate; print(load_and_validate("config/site.yml")["packages"]["source"])')"
  if [[ "${PACKAGE_SOURCE}" == "bundle" ]]; then
    RHEL_GPG_KEY="/etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release"
    if [[ ! -r "${RHEL_GPG_KEY}" ]]; then
      echo "FAIL: required RHEL RPM signing key is unavailable: ${RHEL_GPG_KEY}" >&2
      exit 1
    fi
    rpm --import "${RHEL_GPG_KEY}"
    dnf -y --disablerepo='*' \
      --repofrompath="netbox-offline-base,file://${ROOT_DIR}/artifacts/rpm-repo/base" \
      --repofrompath="netbox-offline-modules,file://${ROOT_DIR}/artifacts/rpm-repo/modules" \
      --enablerepo=netbox-offline-base --enablerepo=netbox-offline-modules \
      install ansible-core
  else
    dnf -q repolist --enabled >/dev/null || {
      echo "FAIL: enabled RHEL repositories are unavailable; registration/subscription must be fixed first." >&2
      exit 1
    }
    dnf -y install ansible-core
  fi
fi

ANSIBLE_CONFIG="${ROOT_DIR}/ansible.cfg" \
  ansible-playbook ansible/site.yml \
  --extra-vars "bundle_root=${ROOT_DIR}" \
  --extra-vars "site_config_file=${ROOT_DIR}/config/site.yml" \
  --extra-vars "secrets_file=${ROOT_DIR}/config/secrets.yml"
