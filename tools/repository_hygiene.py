#!/usr/bin/env python3
"""Secret/size hygiene scan for the current tree and every reachable Git blob."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_BLOB = 10 * 1024 * 1024
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env|id_(rsa|ed25519)|secrets\.yml|.*\.(dump|iso|qcow2|vmdk|ova|bak|backup))$", re.I)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(rb"(?im)^\s*(?:SECRET_KEY|DB_PASSWORD|DATABASE_PASSWORD|API_TOKEN|GITHUB_TOKEN)\s*[:=]\s*['\"]?(?!<|\{\{|\$|ci-only-)[A-Za-z0-9_./+=-]{12,}"),
)

def git(*args):
    return subprocess.run(("git", *args), text=False, capture_output=True, check=False)

def inspect(label, data, size, failures):
    if size > MAX_BLOB:
        failures.append((label, f"large blob ({size} bytes)")); return
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            failures.append((label, "credential/private-key pattern")); return

def main():
    root = Path(__file__).resolve().parents[1]
    failures = []
    tracked = git("-C", str(root), "ls-files", "-z")
    for raw in tracked.stdout.split(b"\0"):
        if not raw: continue
        relative = raw.decode(errors="replace")
        if FORBIDDEN_NAMES.search(relative): failures.append((relative, "forbidden tracked filename"))
        path = root / relative
        if path.is_file():
            data = path.read_bytes(); inspect(relative, data, len(data), failures)
    objects = git("-C", str(root), "rev-list", "--objects", "--all")
    seen = set()
    for line in objects.stdout.splitlines():
        fields = line.split(b" ", 1); oid = fields[0].decode()
        if oid in seen: continue
        seen.add(oid)
        kind = git("-C", str(root), "cat-file", "-t", oid)
        if kind.stdout.strip() != b"blob": continue
        size_result = git("-C", str(root), "cat-file", "-s", oid)
        size = int(size_result.stdout or b"0")
        name = fields[1].decode(errors="replace") if len(fields) > 1 else oid[:12]
        if FORBIDDEN_NAMES.search(name): failures.append((f"history:{name}", "forbidden historical filename"))
        data = b"" if size > MAX_BLOB else git("-C", str(root), "cat-file", "-p", oid).stdout
        inspect(f"history:{name}@{oid[:12]}", data, size, failures)
    if failures:
        for label, reason in sorted(set(failures)):
            print(f"[FAIL] {label} — {reason}")
        print(f"REPOSITORY_HYGIENE=FAIL count={len(set(failures))}")
        return 1
    print(f"REPOSITORY_HYGIENE=PASS tracked={len([p for p in tracked.stdout.split(bytes([0])) if p])} git_objects={len(seen)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
