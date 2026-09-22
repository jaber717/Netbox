#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MODE="install"
if [[ "${1:-}" == "--preflight" ]]; then
  MODE="preflight"
elif [[ $# -gt 0 ]]; then
  echo "Usage: sudo ./install.sh [--preflight]" >&2
  exit 2
fi
[[ ${EUID} -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

cd "${ROOT_DIR}"
python3 tools/prepare_site.py
if [[ "${MODE}" == "preflight" ]]; then
  exec python3 tools/preflight.py --root "${ROOT_DIR}" --allow-missing-secrets
fi
python3 tools/initialize_secrets.py --output config/secrets.yml
exec ./bootstrap.sh
