#!/usr/bin/env python3
"""Write stable, non-secret managed release metadata."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--platform-version", required=True)
    parser.add_argument("--netbox-version", required=True)
    parser.add_argument("--subnet-map-version", required=True)
    parser.add_argument("--installation-mode", required=True)
    parser.add_argument("--upgrade-from")
    args = parser.parse_args()
    target = Path(args.output)
    previous = {}
    if target.is_file():
        previous = json.loads(target.read_text(encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    last_upgrade = args.upgrade_from or previous.get("last_upgrade_version")
    if previous.get("platform_version") and previous.get("platform_version") != args.platform_version:
        last_upgrade = previous["platform_version"]
    state = {
        "managed_by": "netbox-platform",
        "platform_version": args.platform_version,
        "netbox_version": args.netbox_version,
        "subnet_map_version": args.subnet_map_version,
        "installation_mode": args.installation_mode,
        "os": platform.freedesktop_os_release().get("PRETTY_NAME", "unknown"),
        "architecture": platform.machine(),
        "installed_at": previous.get("installed_at", now),
        "last_upgrade_version": last_upgrade,
    }
    rendered = json.dumps(state, indent=2, sort_keys=True) + "\n"
    changed = not target.is_file() or target.read_text(encoding="utf-8") != rendered
    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.chmod(temporary, 0o644)
        temporary.replace(target)
    print(f"RELEASE_STATE_CHANGED={int(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
