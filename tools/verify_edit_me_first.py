#!/usr/bin/env python3
"""Verify EDIT-ME-FIRST coverage against the complete site.yml leaf schema."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_config import load_and_validate  # noqa: E402


def leaves(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    result: set[str] = set()
    for key, child in value.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        result.update(leaves(child, dotted))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--document", required=True)
    args = parser.parse_args()
    schema = leaves(load_and_validate(args.config))
    text = Path(args.document).read_text(encoding="utf-8")
    block = re.search(
        r"<!-- CONFIG-SCHEMA-KEYS-BEGIN -->\s*(.*?)\s*<!-- CONFIG-SCHEMA-KEYS-END -->",
        text,
        flags=re.DOTALL,
    )
    if not block:
        print("[AUD-DOC-001] FAIL — schema coverage block is missing")
        return 1
    documented_list = re.findall(r"^- `([a-z0-9_.-]+)`$", block.group(1), flags=re.MULTILINE)
    documented = set(documented_list)
    missing = sorted(schema - documented)
    extra = sorted(documented - schema)
    duplicates = sorted({key for key in documented_list if documented_list.count(key) > 1})
    if missing or extra or duplicates:
        print(
            "[AUD-DOC-001] FAIL — "
            f"missing={missing} extra={extra} duplicates={duplicates}"
        )
        return 1
    print(f"[AUD-DOC-001] PASS — documented_keys={len(documented)} schema_keys={len(schema)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
