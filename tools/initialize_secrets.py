#!/usr/bin/env python3
"""Create one private secrets file without emitting any secret value."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="config/secrets.yml")
    parser.add_argument("--admin-password-file", help="mode-0600 file containing only the initial admin password")
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        print(f"Secrets already exist at {target}; no values changed.")
        return 0

    if args.admin_password_file:
        password_file = Path(args.admin_password_file)
        if password_file.stat().st_mode & 0o077:
            raise SystemExit("admin password file must not be accessible by group/other")
        admin_password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
    else:
        admin_password = getpass.getpass("Initial NetBox admin password (input hidden): ")
    if not admin_password:
        raise SystemExit("admin password must not be empty")

    generated = {
        "django_secret_key": secrets.token_urlsafe(64),
        "api_token_pepper_1": secrets.token_urlsafe(48),
        "postgresql_password": secrets.token_urlsafe(36),
        "redis_password": secrets.token_urlsafe(36),
        "admin_password": admin_password,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for key, value in generated.items():
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                stream.write(f'{key}: "{escaped}"\n')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print(f"Created {target} with mode 0600. No secret values were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

