#!/usr/bin/env python3
"""Secret-safe release tree audit with stable release-gate IDs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SECRET_KEYS = {
    "django_secret_key",
    "api_token_pepper_1",
    "postgresql_password",
    "redis_password",
    "admin_password",
}


def canonical_values(path: Path) -> list[bytes]:
    values: list[bytes] = []
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_]+):\s*(.*?)\s*$", line)
        if not match or match.group(1) not in SECRET_KEYS:
            continue
        value = match.group(2).strip().strip("'\"")
        if value and not value.startswith("<") and len(value) >= 8:
            values.append(value.encode())
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--classification", choices=("distributable", "private-checkpoint"), required=True)
    parser.add_argument("--private-values-from", help="canonical private secrets file used only for exact-value leak comparison")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    canonical = root / "config/secrets.yml"
    failures: list[tuple[str, str]] = []

    if args.classification == "distributable" and canonical.exists():
        failures.append(("AUD-SEC-001", "config/secrets.yml exists in distributable tree"))
    if args.classification == "private-checkpoint" and not canonical.is_file():
        failures.append(("AUD-SEC-001", "private checkpoint lacks canonical config/secrets.yml"))

    comparison_source = Path(args.private_values_from).resolve() if args.private_values_from else canonical
    private_values = canonical_values(comparison_source)
    if args.private_values_from and not private_values:
        failures.append(("AUD-SEC-004", "external private comparison source is missing or invalid"))
    private_key_markers = tuple(
        (b"-----" + b"BEGIN " + prefix + b"PRIVATE KEY" + b"-----")
        for prefix in (b"", b"RSA ", b"EC ", b"OPENSSH ")
    )
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix()
        lower_name = path.name.lower()
        if path != canonical and (
            lower_name == ".env"
            or lower_name.startswith(("id_rsa", "id_ed25519"))
            or "private_key" in lower_name
            or "private-key" in lower_name
            or (lower_name.startswith("secrets.") and not lower_name.endswith(".example"))
        ):
            failures.append(("AUD-SEC-002", f"forbidden secret-like file name: {relative}"))
        if path == canonical:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(marker in data for marker in private_key_markers):
            failures.append(("AUD-SEC-003", f"private-key material marker: {relative}"))
        if private_values and any(value in data for value in private_values):
            failures.append(("AUD-SEC-004", f"private secret literal outside canonical file: {relative}"))

    if failures:
        for audit_id, detail in failures:
            print(f"[{audit_id}] FAIL — {detail}")
        print(f"SECRET_AUDIT: FAIL={len(failures)}")
        return 1

    print(f"[AUD-SEC-001] PASS — classification={args.classification}")
    print("[AUD-SEC-002] PASS — no forbidden credential/key files")
    print("[AUD-SEC-003] PASS — no private-key material")
    comparison = "external private build input" if args.private_values_from else "canonical private file"
    print(f"[AUD-SEC-004] PASS — no private secret literals outside the allowed boundary; comparison={comparison}")
    print("SECRET_AUDIT: FAIL=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
