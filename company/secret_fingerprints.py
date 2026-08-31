#!/usr/bin/env python3
"""Emit only non-secret generation fingerprints for restore compatibility."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


def parse(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_]+):\s*(.*?)\s*$", line)
        if match:
            result[match.group(1)] = match.group(2).strip().strip("'\"")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets", required=True)
    args = parser.parse_args()
    values = parse(Path(args.secrets))
    secret_key = values.get("django_secret_key", "")
    peppers = []
    for key, value in values.items():
        match = re.fullmatch(r"api_token_pepper_([0-9]+)", key)
        if match:
            peppers.append((int(match.group(1)), value))
    if not secret_key or not peppers or any(not value for _, value in peppers):
        raise SystemExit("required secret values are unavailable for fingerprinting")

    secret_key_digest = hashlib.sha256(secret_key.encode()).hexdigest()
    pepper_digest = hashlib.sha256()
    for pepper_id, value in sorted(peppers, key=lambda item: item[0]):
        encoded = value.encode()
        pepper_digest.update(str(pepper_id).encode())
        pepper_digest.update(b"\0")
        pepper_digest.update(str(len(encoded)).encode())
        pepper_digest.update(b"\0")
        pepper_digest.update(encoded)
        pepper_digest.update(b"\0")

    print(f"django_secret_key_sha256={secret_key_digest}")
    print(f"api_token_peppers_sha256={pepper_digest.hexdigest()}")
    print("api_token_peppers_canonical_order=numeric_id_ascending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
