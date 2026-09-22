#!/usr/bin/env python3
"""Read-only preflight for fresh or platform-managed RHEL 9.x hosts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

from site_config import ConfigError, load_and_validate, require


class Results:
    def __init__(self):
        self.passed = self.warned = self.failed = 0

    def emit(self, level, label, detail=""):
        print(f"[{level}] {label}" + (f" — {detail}" if detail else ""))
        if level == "PASS": self.passed += 1
        elif level == "WARN": self.warned += 1
        else: self.failed += 1

    def check(self, condition, label, detail=""):
        self.emit("PASS" if condition else "FAIL", label, detail)


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=False)


def os_release():
    values = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root, results):
    manifest = root / "manifest" / "SHA256SUMS"
    if not manifest.is_file():
        results.emit("FAIL", "Offline manifest", "manifest/SHA256SUMS missing")
        return
    failed = []
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        target = root / relative.lstrip(" *")
        if not target.is_file() or sha256(target) != expected:
            failed.append(str(target.relative_to(root)))
        checked += 1
    results.check(checked > 0 and not failed, "Offline bundle integrity", f"checked={checked} mismatches={len(failed)}")


def installation_state():
    marker = Path("/etc/netbox-platform/release.json")
    managed = Path("/etc/netbox/.managed-by-netbox-platform")
    marker_valid = managed.is_file() and managed.read_text(encoding="utf-8", errors="replace").startswith("NETBOX-PLATFORM ")
    if marker.is_file() and marker_valid:
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            if state.get("managed_by") == "netbox-platform":
                return "MANAGED-CONVERGE", "valid release state"
        except (OSError, ValueError):
            pass
        return "CONFLICT", "managed marker/release state is invalid"
    if marker_valid:
        return "MANAGED-CONVERGE", "valid partial-install marker; release state not written yet"
    if any(path.exists() for path in (Path("/opt/netbox"), Path("/etc/netbox/configuration.py"))):
        return "CONFLICT", "an unmanaged NetBox installation exists"
    listeners = run("ss", "-H", "-lnt")
    occupied = []
    for line in listeners.stdout.splitlines():
        endpoint = line.split()[3] if len(line.split()) > 3 else ""
        if any(endpoint.endswith(f":{port}") for port in (80, 443, 8001, 5432, 6379)):
            occupied.append(endpoint)
    if occupied:
        return "CONFLICT", "required ports are already in use: " + ", ".join(sorted(set(occupied)))
    return "FRESH", "no existing platform detected"


def check_https(url, results):
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "netbox-platform-preflight"})
        with urllib.request.urlopen(request, timeout=15, context=ssl.create_default_context()) as response:
            ok = 200 <= response.status < 400
    except Exception as exc:
        results.emit("FAIL", f"TLS connectivity {url}", type(exc).__name__)
    else:
        results.check(ok, f"TLS connectivity {url}", f"HTTP {response.status}")


def load_secrets(path):
    from site_config import load_simple_yaml
    values = load_simple_yaml(path)
    required = {"django_secret_key", "api_token_pepper_1", "postgresql_password", "redis_password", "admin_password"}
    if set(values) != required:
        raise ConfigError("secret field names do not match the required schema")
    if any(not isinstance(values[key], str) or not values[key] or values[key].startswith("<") for key in required):
        raise ConfigError("a secret is empty or still a placeholder")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--config", default="config/site.yml")
    parser.add_argument("--secrets", default="config/secrets.yml")
    parser.add_argument("--allow-missing-secrets", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    results = Results()
    try:
        config = load_and_validate(root / args.config)
        results.emit("PASS", "Configuration schema", args.config)
    except (OSError, ConfigError, ValueError) as exc:
        results.emit("FAIL", "Configuration schema", str(exc))
        config = None

    release = os_release() if Path("/etc/os-release").is_file() else {}
    version = release.get("VERSION_ID", "")
    results.check(release.get("ID") == "rhel" and bool(re.fullmatch(r"9\.[0-9]+", version)),
                  "RHEL 9.x", release.get("PRETTY_NAME", "unknown"))
    results.check(platform.machine() == "x86_64", "Architecture x86_64", platform.machine())
    results.check((os.cpu_count() or 0) >= 2, "CPU capacity", f"{os.cpu_count() or 0} logical CPUs")
    memory_kib = 0
    if Path("/proc/meminfo").is_file():
        memory_kib = int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1])
    results.check(memory_kib >= 4 * 1024 * 1024, "Memory capacity", f"{memory_kib // 1024} MiB")
    free_gib = shutil.disk_usage("/").free / 1024**3
    results.check(free_gib >= 15, "Disk capacity", f"{free_gib:.1f} GiB free")
    enforcing = run("getenforce") if shutil.which("getenforce") else None
    results.check(bool(enforcing and enforcing.stdout.strip() == "Enforcing"), "SELinux Enforcing",
                  enforcing.stdout.strip() if enforcing else "getenforce unavailable")

    state, detail = installation_state()
    results.emit("FAIL" if state == "CONFLICT" else "PASS", f"Installation state {state}", detail)
    print(f"INSTALLATION_STATE={state}")

    if config:
        source = require(config, "packages.source")
        if source == "connected":
            repos = run("dnf", "-q", "repolist", "--enabled")
            results.check(repos.returncode == 0 and len(repos.stdout.splitlines()) > 1,
                          "Enabled RHEL repositories", "dnf repolist succeeded" if repos.returncode == 0 else "dnf unavailable/unregistered")
            check_https("https://github.com/", results)
            check_https("https://pypi.org/", results)
        else:
            verify_manifest(root, results)
            results.check((root / "artifacts/upstream/netbox-4.6.9.tar.gz").is_file(), "Offline NetBox source")
            results.check(any((root / "artifacts/wheelhouse").glob("*.whl")), "Offline Python wheelhouse")
        results.check((root / "plugins/netbox-subnet-map/pyproject.toml").is_file(), "Vendored Subnet Map source")

    secrets_path = root / args.secrets
    if secrets_path.is_file():
        mode = stat.S_IMODE(secrets_path.stat().st_mode)
        results.check(mode & 0o077 == 0, "Secrets permissions", f"mode={mode:04o}")
        try:
            load_secrets(secrets_path)
            results.emit("PASS", "Secrets schema")
        except (OSError, ConfigError, ValueError) as exc:
            results.emit("FAIL", "Secrets schema", str(exc))
    elif args.allow_missing_secrets:
        results.emit("WARN", "Secrets file", "not created during preflight-only mode")
    else:
        results.emit("FAIL", "Secrets file", f"missing {secrets_path}")

    print(f"\nPREFLIGHT: {results.passed} PASS, {results.warned} WARN, {results.failed} FAIL")
    return 1 if results.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
