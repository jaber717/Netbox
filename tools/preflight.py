#!/usr/bin/env python3
"""Read-only preflight for a clean or already managed RHEL 9.6 host."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

from site_config import ConfigError, load_and_validate, require


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.warned = 0
        self.failed = 0

    def emit(self, level: str, label: str, detail: str = "") -> None:
        suffix = f" — {detail}" if detail else ""
        print(f"[{level}] {label}{suffix}")
        if level == "PASS":
            self.passed += 1
        elif level == "WARN":
            self.warned += 1
        else:
            self.failed += 1

    def check(self, condition: bool, label: str, detail: str = "") -> None:
        self.emit("PASS" if condition else "FAIL", label, detail)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root: Path, results: Results) -> None:
    manifest = root / "manifest" / "SHA256SUMS"
    if not manifest.is_file():
        results.emit("FAIL", "Bundle integrity manifest", "manifest/SHA256SUMS is missing")
        return
    failures = []
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.lstrip(" *")
        target = root / relative
        if not target.is_file() or file_sha256(target) != expected:
            failures.append(relative)
        checked += 1
    results.check(not failures and checked > 0, "Bundle integrity", f"{checked} files checked; mismatches={len(failures)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--config", default="config/site.yml")
    parser.add_argument("--secrets", default="config/secrets.yml")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config_path = (root / args.config).resolve()
    secrets_path = (root / args.secrets).resolve()
    results = Results()

    try:
        config = load_and_validate(config_path)
        results.emit("PASS", "Configuration schema", str(config_path))
    except (OSError, ConfigError, ValueError) as exc:
        results.emit("FAIL", "Configuration schema", str(exc))
        config = {}

    if Path("/etc/os-release").is_file():
        release = os_release()
        results.check(release.get("ID") == "rhel" and release.get("VERSION_ID") == "9.6", "RHEL exactly 9.6", f"detected {release.get('PRETTY_NAME', 'unknown')}")
    else:
        results.emit("FAIL", "RHEL exactly 9.6", "/etc/os-release missing")
    results.check(platform.machine() == "x86_64", "Architecture x86_64", platform.machine())
    results.check((os.cpu_count() or 0) >= 2, "CPU capacity", f"{os.cpu_count() or 0} logical CPUs")

    memory_kib = 0
    if Path("/proc/meminfo").is_file():
        first = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()[0]
        memory_kib = int(first.split()[1])
    results.check(memory_kib >= 4 * 1024 * 1024, "Memory capacity", f"{memory_kib // 1024} MiB")
    free_gib = shutil.disk_usage("/").free / 1024**3
    results.check(free_gib >= 15, "Disk capacity", f"{free_gib:.1f} GiB free")

    enforcing = run("getenforce") if shutil.which("getenforce") else None
    results.check(bool(enforcing and enforcing.stdout.strip() == "Enforcing"), "SELinux Enforcing", enforcing.stdout.strip() if enforcing else "getenforce unavailable")

    if config:
        expected_host = require(config, "server.hostname")
        detected_host = socket.gethostname().split(".", 1)[0]
        results.check(detected_host == expected_host, "Hostname assertion", f"expected={expected_host} detected={detected_host}")

        interface = require(config, "expected_network.interface")
        address_result = run("ip", "-j", "address", "show", "dev", interface)
        detected_cidrs: list[str] = []
        if address_result.returncode == 0:
            for item in json.loads(address_result.stdout or "[]"):
                for address in item.get("addr_info", []):
                    if address.get("family") == "inet":
                        detected_cidrs.append(f"{address['local']}/{address['prefixlen']}")
        expected_cidr = str(require(config, "expected_network.cidr"))
        results.check(expected_cidr in detected_cidrs, "Interface/IP assertion", f"{interface}: expected={expected_cidr} detected={','.join(detected_cidrs) or 'none'}")

        route = run("ip", "-j", "route", "show", "default")
        gateways = [item.get("gateway") for item in json.loads(route.stdout or "[]") if item.get("gateway")]
        expected_gateway = require(config, "expected_network.gateway")
        results.check(expected_gateway in gateways, "Gateway assertion", f"expected={expected_gateway} detected={','.join(gateways) or 'none'}")

        resolvers = []
        if Path("/etc/resolv.conf").is_file():
            for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("nameserver "):
                    resolvers.append(line.split()[1])
        expected_dns = [str(item) for item in require(config, "expected_network.dns")]
        results.check(all(item in resolvers for item in expected_dns), "DNS resolver assertion", f"expected={','.join(expected_dns)} detected={','.join(resolvers) or 'none'}")
        try:
            socket.getaddrinfo(require(config, "server.fqdn"), 443)
            results.emit("PASS", "DNS name resolution", require(config, "server.fqdn"))
        except socket.gaierror as exc:
            results.emit("FAIL", "DNS name resolution", str(exc))

        ntp = run("timedatectl", "show", "-p", "NTPSynchronized", "--value")
        synchronized = ntp.returncode == 0 and ntp.stdout.strip().lower() == "yes"
        if synchronized:
            results.emit("PASS", "NTP synchronized")
        elif require(config, "expected_network.require_ntp_synchronized"):
            results.emit("FAIL", "NTP synchronized", "timedatectl reports no")
        else:
            results.emit("WARN", "NTP synchronized", "not synchronized; policy is warning-only")

        final_marker = Path("/etc/netbox/.managed-by-netbox-rhel96-offline").is_file()
        bundle_repo_markers = all(
            Path(f"/etc/yum.repos.d/{name}.repo").is_file()
            for name in ("netbox-offline-base", "netbox-offline-modules")
        )
        managed = final_marker or bundle_repo_markers
        listeners = run("ss", "-H", "-lnt")
        conflicts = []
        for line in listeners.stdout.splitlines():
            endpoint = line.split()[3] if len(line.split()) > 3 else ""
            if any(endpoint.endswith(f":{port}") for port in (80, 443, 8001, 5432, 6379)):
                conflicts.append(endpoint)
        if conflicts and not managed:
            results.emit("FAIL", "Port conflicts", ", ".join(sorted(set(conflicts))))
        elif managed:
            state = "completed" if final_marker else "partial"
            results.emit("PASS", "Managed rerun detection", f"{state} bundle-owned installation allowed")
        else:
            results.emit("PASS", "Port conflicts", "none")

        existing = Path("/opt/netbox").exists()
        results.check(not existing or managed, "Existing NetBox installation", "managed rerun" if managed else "none")

        source = require(config, "packages.source")
        if source == "bundle":
            base_repomd = root / "artifacts/rpm-repo/base/repodata/repomd.xml"
            module_repomd = root / "artifacts/rpm-repo/modules/repodata/repomd.xml"
            results.check(base_repomd.is_file() and module_repomd.is_file(), "Offline RPM repository metadata", "base and modular repositories")
        else:
            results.emit("PASS", "Package source", "satellite (explicit)")

        wheels = list((root / "artifacts/wheelhouse").glob("*.whl"))
        results.check(bool(wheels), "Python wheelhouse", f"{len(wheels)} wheels")
        netbox_tar = root / "artifacts/upstream/netbox-4.6.9.tar.gz"
        results.check(netbox_tar.is_file(), "NetBox 4.6.9 source archive", str(netbox_tar))

        tls_mode = require(config, "tls.mode")
        if tls_mode == "supplied":
            cert = Path(require(config, "tls.certificate"))
            key = Path(require(config, "tls.private_key"))
            results.check(cert.is_file() and key.is_file(), "Supplied TLS files", f"certificate={cert} key={key}")
        else:
            results.emit("WARN", "TLS mode", "self_signed_dev; replace for production")

    verify_manifest(root, results)

    if secrets_path.is_file():
        mode = stat.S_IMODE(secrets_path.stat().st_mode)
        results.check(mode & 0o077 == 0, "Secrets file permissions", f"mode={mode:04o}")
        try:
            secrets = load_and_validate_secrets(secrets_path)
            results.emit("PASS", "Secrets file fields", f"{len(secrets)} required keys present")
        except (OSError, ConfigError, ValueError) as exc:
            results.emit("FAIL", "Secrets file fields", str(exc))
    else:
        results.emit("FAIL", "Secrets file", f"missing {secrets_path}")

    print(f"\nPREFLIGHT: {results.passed} PASS, {results.warned} WARN, {results.failed} FAIL")
    return 1 if results.failed else 0


def load_and_validate_secrets(path: Path) -> dict[str, str]:
    from site_config import load_simple_yaml

    values = load_simple_yaml(path)
    required_keys = {"django_secret_key", "api_token_pepper_1", "postgresql_password", "redis_password", "admin_password"}
    if set(values) != required_keys:
        missing = required_keys - set(values)
        extra = set(values) - required_keys
        raise ConfigError(f"secret keys mismatch; missing={sorted(missing)} extra={sorted(extra)}")
    for key in required_keys:
        value = values[key]
        if not isinstance(value, str) or not value or value.startswith("<"):
            raise ConfigError(f"{key} is empty or still a placeholder")
    return values


if __name__ == "__main__":
    sys.exit(main())
