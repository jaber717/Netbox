#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
RESUME=false
if [[ "${1:-}" == "--resume" ]]; then
  RESUME=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: sudo ./build/build-offline-bundle.sh [--resume]" >&2
  exit 2
fi
VERSION="1.0.0-rc1"
PRODUCT="NETBOX-PLATFORM-OFFLINE-${VERSION}"
WORK_DIR="${ROOT_DIR}/build-work"
RPM_ROOT="${ROOT_DIR}/artifacts/rpm-repo"
WHEELHOUSE="${ROOT_DIR}/artifacts/wheelhouse"
UPSTREAM="${ROOT_DIR}/artifacts/upstream"
DIST="${ROOT_DIR}/dist"

fail() { echo "BUILD FAIL: $*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail "run with sudo on a registered RHEL 9.x x86_64 build host"
[[ -f /etc/redhat-release ]] || fail "not RHEL"
grep -Eq 'Red Hat Enterprise Linux release 9\.[0-9]+' /etc/redhat-release || fail "requires RHEL 9.x"
[[ "$(uname -m)" == "x86_64" ]] || fail "requires x86_64"
dnf -q repolist --enabled >/dev/null || fail "enabled RHEL repositories are unavailable"
[[ -f "${ROOT_DIR}/config/secrets.yml" ]] || fail "create config/secrets.yml first"
[[ "$(stat -c '%a' "${ROOT_DIR}/config/secrets.yml")" == "600" ]] || fail "config/secrets.yml must have mode 0600"

chmod 0755 \
  "${ROOT_DIR}/install.sh" "${ROOT_DIR}/verify.sh" "${ROOT_DIR}/bootstrap.sh" "${ROOT_DIR}/backup.sh" "${ROOT_DIR}/restore.sh" \
  "${ROOT_DIR}/upgrade.sh" "${ROOT_DIR}/build/build-offline-bundle.sh" \
  "${ROOT_DIR}/build/create-sanitized-release.sh" \
  "${ROOT_DIR}/tools/generate_manifest.py" "${ROOT_DIR}/tools/initialize_secrets.py" \
  "${ROOT_DIR}/tools/preflight.py" "${ROOT_DIR}/tools/secret_audit.py" "${ROOT_DIR}/tools/release_state.py" \
  "${ROOT_DIR}/tools/prepare_site.py" "${ROOT_DIR}/company/backup.sh" \
  "${ROOT_DIR}/company/restore.sh" "${ROOT_DIR}/company/verify_restore.sh" \
  "${ROOT_DIR}/company/secret_fingerprints.py" "${ROOT_DIR}/acceptance/verify.py"

ONLINE_REPO_EXCLUDES=(
  --disablerepo=netbox-offline-base
  --disablerepo=netbox-offline-modules
)
dnf -y "${ONLINE_REPO_EXCLUDES[@]}" install dnf-plugins-core python3-dnf-plugin-modulesync createrepo_c python3.12 python3.12-pip tar gzip rsync

if [[ "${RESUME}" == false ]]; then
  for target in "${WORK_DIR}" "${RPM_ROOT}/base" "${RPM_ROOT}/modules" "${WHEELHOUSE}" "${UPSTREAM}" "${DIST}/${PRODUCT}"; do
    [[ "${target}" == "${ROOT_DIR}"* ]] || fail "refusing unsafe build target: ${target}"
    rm -rf -- "${target}"
  done
else
  for target in "${WORK_DIR}/wheel-build-venv" "${WORK_DIR}/offline-wheel-test" "${WORK_DIR}/dnf-test-root" "${WHEELHOUSE}" "${DIST}/${PRODUCT}"; do
    [[ "${target}" == "${ROOT_DIR}"* ]] || fail "refusing unsafe resume target: ${target}"
    rm -rf -- "${target}"
  done
fi
install -d -m 0755 "${WORK_DIR}" "${RPM_ROOT}/base" "${RPM_ROOT}/modules" "${WHEELHOUSE}" "${UPSTREAM}" "${DIST}"

if [[ ! -f "${UPSTREAM}/netbox-4.6.9.tar.gz" ]]; then
  echo "Downloading official NetBox 4.6.9 source archive..."
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "${UPSTREAM}/netbox-4.6.9.tar.gz" \
    https://github.com/netbox-community/netbox/archive/refs/tags/v4.6.9.tar.gz
fi
[[ "$(sha256sum "${UPSTREAM}/netbox-4.6.9.tar.gz" | cut -d' ' -f1)" == "b0c4431a0edc7ce7b019e3f339e944400bf8e628cefa92260a4784f218a67f7c" ]] || fail "NetBox source checksum mismatch"
tar -tzf "${UPSTREAM}/netbox-4.6.9.tar.gz" > "${WORK_DIR}/netbox-archive-files.txt"
grep -Fxq 'netbox-4.6.9/netbox/manage.py' "${WORK_DIR}/netbox-archive-files.txt" || fail "unexpected NetBox archive layout"
if [[ ! -f "${WORK_DIR}/netbox-4.6.9/netbox/manage.py" ]]; then
  tar -C "${WORK_DIR}" -xzf "${UPSTREAM}/netbox-4.6.9.tar.gz"
fi

if [[ ! -f "${RPM_ROOT}/modules/repodata/repomd.xml" ]]; then
  echo "Building modular repository with preserved modulemd..."
  dnf -y modulesync --newest-only --resolve \
    --destdir "${RPM_ROOT}/modules" \
    postgresql:16 nginx:1.24
fi
grep -q 'modules' "${RPM_ROOT}/modules/repodata/repomd.xml" || fail "modular repository lacks module metadata"

BASE_PACKAGES=(
  ansible-core python3.12 python3.12-pip redis firewalld
  policycoreutils-python-utils python3-libselinux python3-firewall
  rsync tar gzip openssl ca-certificates shadow-utils sudo curl
)
if [[ ! -f "${RPM_ROOT}/base/repodata/repomd.xml" ]]; then
  echo "Resolving non-modular RHEL package closure..."
  dnf -y download "${ONLINE_REPO_EXCLUDES[@]}" --resolve --alldeps --arch=x86_64,noarch \
    --destdir "${RPM_ROOT}/base" "${BASE_PACKAGES[@]}"
  createrepo_c --database "${RPM_ROOT}/base"
fi

echo "Building complete Python 3.12 wheelhouse..."
python3.12 -m venv "${WORK_DIR}/wheel-build-venv"
"${WORK_DIR}/wheel-build-venv/bin/python" -m pip wheel \
  --prefer-binary \
  --wheel-dir "${WHEELHOUSE}" \
  --requirement "${WORK_DIR}/netbox-4.6.9/requirements.txt" \
  gunicorn PyYAML
"${WORK_DIR}/wheel-build-venv/bin/python" -m pip wheel \
  --wheel-dir "${WHEELHOUSE}" "${ROOT_DIR}/plugins/netbox-subnet-map"

echo "Rehearsing wheelhouse with indexes disabled..."
python3.12 -m venv "${WORK_DIR}/offline-wheel-test"
PIP_NO_INDEX=1 "${WORK_DIR}/offline-wheel-test/bin/pip" install \
  --no-index --find-links "${WHEELHOUSE}" \
  --requirement "${WORK_DIR}/netbox-4.6.9/requirements.txt" gunicorn PyYAML
"${WORK_DIR}/offline-wheel-test/bin/pip" check
PIP_NO_INDEX=1 "${WORK_DIR}/offline-wheel-test/bin/python" -c 'import django, gunicorn, netaddr, psycopg, redis, yaml'

echo "Testing local DNF module resolution with external repositories disabled..."
DNF_TEST="${WORK_DIR}/dnf-test-root"
install -d -m 0755 "${DNF_TEST}"
DNF_LOCAL=(
  --refresh
  --disableplugin=subscription-manager
  --setopt=cachedir="${WORK_DIR}/dnf-offline-cache"
  --installroot="${DNF_TEST}"
  --releasever=9
  --setopt=module_platform_id=platform:el9
  --setopt=install_weak_deps=False
  --disablerepo='*'
  --repofrompath="netbox-build-test-base,file://${RPM_ROOT}/base"
  --repofrompath="netbox-build-test-modules,file://${RPM_ROOT}/modules"
  --enablerepo=netbox-build-test-base
  --enablerepo=netbox-build-test-modules
  --nogpgcheck
)
dnf -y "${DNF_LOCAL[@]}" module enable postgresql:16 nginx:1.24
dnf -y "${DNF_LOCAL[@]}" install ansible-core python3.12 postgresql-server postgresql-contrib redis nginx firewalld policycoreutils-python-utils rsync

echo "Generating manifests..."
install -d -m 0755 "${ROOT_DIR}/manifest"
python3 "${ROOT_DIR}/tools/generate_manifest.py" --root "${ROOT_DIR}"

echo "Creating expanded and compressed transfer artifacts..."
STAGE="${DIST}/${PRODUCT}"
install -d -m 0755 "${STAGE}"
rsync -a \
  --exclude '/.git/' --exclude '/build-work/' --exclude '/dist/' \
  --exclude '__pycache__/' --exclude '*.pyc' \
  "${ROOT_DIR}/" "${STAGE}/"
chmod 0600 "${STAGE}/config/secrets.yml"
python3 "${STAGE}/tools/generate_manifest.py" --root "${STAGE}"

PRIVATE_ARCHIVE="${DIST}/${PRODUCT}-PRIVATE-CHECKPOINT.tar.gz"
rm -f -- "${PRIVATE_ARCHIVE}" "${PRIVATE_ARCHIVE}.sha256" \
  "${DIST}/${PRODUCT}.tar.gz" "${DIST}/${PRODUCT}.tar.gz.sha256"
tar --owner=0 --group=0 --numeric-owner -C "${DIST}" -czf "${PRIVATE_ARCHIVE}" "${PRODUCT}"
sha256sum "${PRIVATE_ARCHIVE}" > "${PRIVATE_ARCHIVE}.sha256"
chmod 0600 "${PRIVATE_ARCHIVE}" "${PRIVATE_ARCHIVE}.sha256"
"${ROOT_DIR}/build/create-sanitized-release.sh" \
  --source-root "${STAGE}" --output-dir "${DIST}"
chown -R "${SUDO_USER:-root}:${SUDO_USER:-root}" "${DIST}" "${ROOT_DIR}/manifest" "${ROOT_DIR}/artifacts"

echo "BUILD COMPLETE"
du -h "${DIST}/${PRODUCT}.tar.gz" "${PRIVATE_ARCHIVE}"
sha256sum "${DIST}/${PRODUCT}.tar.gz" "${PRIVATE_ARCHIVE}"
