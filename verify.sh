#!/usr/bin/env bash
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ -x /usr/local/sbin/netbox-verify ]] || { echo "FAIL: managed verification command is not installed." >&2; exit 1; }
exec /usr/local/sbin/netbox-verify
