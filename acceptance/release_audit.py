#!/usr/bin/env python3
"""Deterministic, secret-safe final release audit and evidence collector."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import platform
import re
import ssl
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path


SERVICES = ("postgresql", "redis", "netbox", "netbox-rq", "nginx", "firewalld")
API_ENDPOINTS = {
    "racks": "/api/dcim/racks/?limit=1",
    "devices": "/api/dcim/devices/?limit=1",
    "cables": "/api/dcim/cables/?limit=1",
    "prefixes": "/api/ipam/prefixes/?limit=1",
    "ip_addresses": "/api/ipam/ip-addresses/?limit=1",
    "vlans": "/api/ipam/vlans/?limit=1",
    "aggregates": "/api/ipam/aggregates/?limit=1",
    "circuits": "/api/circuits/circuits/?limit=1",
    "circuit_terminations": "/api/circuits/circuit-terminations/?limit=1",
}


def run(argv: list[str], cwd: str = "/") -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def parse_secret_values(path: Path) -> list[bytes]:
    values: list[bytes] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^[A-Za-z0-9_]+:\s*(.*?)\s*$", line)
        if not match:
            continue
        value = match.group(1).strip().strip("'\"")
        if value and len(value) >= 8:
            values.append(value.encode())
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/var/lib/netbox/release-evidence")
    args = parser.parse_args()
    evidence = Path(args.output).resolve()
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence.chmod(0o700)
    results: list[dict[str, str]] = []

    def result(audit_id: str, ok: bool, detail: str, warning: bool = False) -> None:
        status = "WARN" if warning else ("PASS" if ok else "FAIL")
        results.append({"id": audit_id, "status": status, "detail": detail})
        print(f"[{audit_id}] {status} — {detail}")

    rpm_list = run(["rpm", "-qa", "--qf", "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n"])
    write(evidence / "installed-rpms.txt", "".join(sorted(rpm_list.stdout.splitlines(keepends=True))))
    pip_list = run(["/opt/netbox/venv/bin/pip", "list", "--format=freeze"])
    write(evidence / "netbox-venv-packages.txt", pip_list.stdout + pip_list.stderr)
    result("AUD-EVD-001", rpm_list.returncode == 0 and pip_list.returncode == 0, "runtime package inventories captured")

    service_lines = []
    services_ok = True
    for service in SERVICES:
        state = run(["systemctl", "is-active", service])
        state_text = state.stdout.strip() or state.stderr.strip()
        service_lines.append(f"{service}={state_text}\n")
        services_ok = services_ok and state.returncode == 0 and state_text == "active"
    write(evidence / "service-states.txt", "".join(service_lines))
    result("AUD-SVC-001", services_ok, "required native services active")

    sockets = run(["ss", "-lntup"])
    write(evidence / "listening-sockets.txt", sockets.stdout + sockets.stderr)
    result("AUD-NET-001", sockets.returncode == 0, "listening sockets captured")

    selinux = run(["getenforce"])
    write(evidence / "selinux-state.txt", selinux.stdout + selinux.stderr)
    result("AUD-SEL-001", selinux.stdout.strip() == "Enforcing", selinux.stdout.strip() or "unavailable")

    firewall = run(["firewall-cmd", "--permanent", "--list-all"])
    write(evidence / "firewalld-state.txt", firewall.stdout + firewall.stderr)
    firewall_443 = run(["firewall-cmd", "--permanent", "--query-port=443/tcp"]).returncode == 0
    forbidden = any(run(["firewall-cmd", "--permanent", f"--query-port={port}/tcp"]).returncode == 0 for port in (5432, 6379, 8001))
    result("AUD-FW-001", firewall.returncode == 0 and firewall_443 and not forbidden, "HTTPS allowed; internal application ports not exposed")

    version_commands = {
        "rhel": ["cat", "/etc/redhat-release"],
        "kernel": ["uname", "-r"],
        "python": ["/opt/netbox/venv/bin/python", "--version"],
        "postgresql": ["psql", "--version"],
        "redis": ["redis-server", "--version"],
        "nginx": ["nginx", "-v"],
    }
    version_output = []
    version_ok = True
    for name, command in version_commands.items():
        completed = run(command)
        version_ok = version_ok and completed.returncode == 0
        version_output.append(f"[{name}]\n{completed.stdout}{completed.stderr}")
    write(evidence / "component-versions.txt", "".join(version_output))
    result("AUD-VER-001", version_ok, "component versions captured")

    registration = run(["subscription-manager", "status"])
    release = run(["subscription-manager", "release", "--show"])
    repolist = run(["dnf", "repolist", "--enabled"])
    write(evidence / "subscription-and-repositories.txt", registration.stdout + registration.stderr + release.stdout + release.stderr + repolist.stdout + repolist.stderr)
    result("AUD-SUB-001", release.returncode == 0 or "not registered" in (release.stdout + release.stderr).lower(), "subscription/registration state recorded without requiring access")

    expected_root = "/opt/netbox-offline-repo/1.0.0"
    repo_parser = configparser.ConfigParser()
    repo_parser.read(["/etc/yum.repos.d/netbox-offline-base.repo", "/etc/yum.repos.d/netbox-offline-modules.repo"])
    expected_urls = {
        "netbox-offline-base": f"file://{expected_root}/base",
        "netbox-offline-modules": f"file://{expected_root}/modules",
    }
    repo_paths_ok = all(
        repo_parser.has_section(repo) and repo_parser.get(repo, "baseurl", fallback="") == url
        for repo, url in expected_urls.items()
    ) and all((Path(expected_root) / part / "repodata/repomd.xml").is_file() for part in ("base", "modules"))
    repo_test = run([
        "dnf", "-y", "--refresh", "--disableplugin=subscription-manager", "--disablerepo=*",
        "--enablerepo=netbox-offline-base", "--enablerepo=netbox-offline-modules", "makecache",
    ], cwd="/")
    write(evidence / "persistent-repository-test.txt", repo_test.stdout + repo_test.stderr)
    result("AUD-REPO-001", repo_paths_ok and repo_test.returncode == 0, "persistent local repositories resolve independently of the transfer directory")

    acceptance = run(["/usr/local/sbin/netbox-acceptance"])
    write(evidence / "acceptance.txt", acceptance.stdout + acceptance.stderr)
    summary_match = re.search(r"^ACCEPTANCE_SUMMARY=(\{.*\})$", acceptance.stdout, flags=re.MULTILINE)
    acceptance_summary = json.loads(summary_match.group(1)) if summary_match else {}
    acceptance_ok = acceptance.returncode == 0 and acceptance_summary.get("fail") == 0 and acceptance_summary.get("skip") == 0 and acceptance_summary.get("total", 0) > 0
    result("AUD-ACC-001", acceptance_ok, f"dynamic_summary={json.dumps(acceptance_summary, sort_keys=True)}")

    # NetBox 4.6 requires authentication for object endpoints. Run a narrowly
    # scoped helper inside NetBox's virtual environment so the token never
    # crosses a command-line argument, output file, or evidence boundary. The
    # helper creates a read-only v1 token, performs real local HTTPS requests,
    # deletes the token in a finally block, and emits counts only.
    token_description = "netbox-rhel96-release-audit-ephemeral-v1"
    api_helper = f"""
import json
import ssl
import urllib.request
from django.contrib.auth import get_user_model
from users.models import Token

endpoints = {API_ENDPOINTS!r}
description = {token_description!r}
counts = {{}}
token = None
Token.objects.filter(description=description).delete()
try:
    user = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
    if user is None:
        raise RuntimeError("no superuser available for release audit")
    token = Token.objects.create(
        user=user,
        version=1,
        description=description,
        write_enabled=False,
    )
    context = ssl._create_unverified_context()
    for name, endpoint in endpoints.items():
        try:
            request = urllib.request.Request(
                f"https://127.0.0.1{{endpoint}}",
                headers={{"Authorization": f"Token {{token.plaintext}}"}},
            )
            with urllib.request.urlopen(request, context=context, timeout=15) as response:
                counts[name] = int(json.load(response)["count"])
        except Exception as exc:
            counts[name] = f"ERROR:{{type(exc).__name__}}"
finally:
    if token is not None:
        Token.objects.filter(pk=token.pk).delete()

print("API_AUDIT_JSON=" + json.dumps({{
    "counts": counts,
    "ephemeral_tokens_remaining": Token.objects.filter(description=description).count(),
}}, sort_keys=True))
"""
    api_audit = run([
        "runuser", "-u", "netbox", "--",
        "/opt/netbox/venv/bin/python", "/opt/netbox/netbox/manage.py",
        "shell", "-c", api_helper,
    ])
    api_marker = re.search(r"^API_AUDIT_JSON=(\{.*\})$", api_audit.stdout, flags=re.MULTILINE)
    api_result = json.loads(api_marker.group(1)) if api_marker else {}
    api_counts = api_result.get("counts", {})
    ephemeral_tokens_remaining = api_result.get("ephemeral_tokens_remaining", -1)
    write(evidence / "api-operational-counts.json", json.dumps(api_counts, indent=2, sort_keys=True) + "\n")
    api_ok = (
        api_audit.returncode == 0
        and set(api_counts) == set(API_ENDPOINTS)
        and all(value == 0 for value in api_counts.values())
        and ephemeral_tokens_remaining == 0
    )
    result(
        "AUD-DATA-001",
        api_ok,
        f"api_counts={json.dumps(api_counts, sort_keys=True)}; ephemeral_tokens_remaining={ephemeral_tokens_remaining}",
    )

    document_check = run([
        "/opt/netbox-company/bin/verify_edit_me_first.py",
        "--config", "/etc/netbox/deployment/site.yml",
        "--document", "/opt/netbox-company/release-docs/EDIT-ME-FIRST.md",
    ])
    write(evidence / "edit-me-first-verification.txt", document_check.stdout + document_check.stderr)
    result("AUD-DOC-001", document_check.returncode == 0, document_check.stdout.strip() or document_check.stderr.strip())

    backup = run(["/usr/local/sbin/netbox-backup"])
    backup_match = re.search(r"^Backup created: (.+)$", backup.stdout, flags=re.MULTILINE)
    restore = run(["/usr/local/sbin/netbox-restore-verify", "--archive", backup_match.group(1)]) if backup_match else None
    write(evidence / "backup-restore-verification.txt", backup.stdout + backup.stderr + (restore.stdout + restore.stderr if restore else "restore verification not started\n"))
    result("AUD-RST-001", backup.returncode == 0 and bool(restore and restore.returncode == 0), "backup completed and isolated scratch restore succeeded")

    compiler_names = ("gcc", "gcc-c++", "make", "python3.12-devel", "libpq-devel", "redhat-rpm-config")
    compiler_lines = []
    present_compilers = []
    for package in compiler_names:
        query = run(["rpm", "-q", package])
        if query.returncode == 0:
            present_compilers.append(package)
            compiler_lines.append(f"PRESENT {query.stdout.strip()}\n")
        else:
            compiler_lines.append(f"ABSENT {package}\n")
    write(evidence / "build-tooling-observation.txt", "".join(compiler_lines))
    result("AUD-BLD-001", True, "clean target runtime installed without build-only tooling" if not present_compilers else f"baseline already contains non-required tooling: {','.join(present_compilers)}", warning=bool(present_compilers))

    os_release = Path("/etc/os-release").read_text(encoding="utf-8")
    addresses = run(["ip", "-j", "-4", "address", "show", "scope", "global"])
    fingerprint_source = {
        "os_release_sha256": hashlib.sha256(os_release.encode()).hexdigest(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "logical_cpu_count": os.cpu_count(),
        "global_ipv4": json.loads(addresses.stdout or "[]"),
    }
    canonical = json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":"))
    fingerprint = {"sha256": hashlib.sha256(canonical.encode()).hexdigest(), "environment": fingerprint_source}
    write(evidence / "environment-fingerprint.json", json.dumps(fingerprint, indent=2, sort_keys=True) + "\n")
    result("AUD-ENV-001", addresses.returncode == 0, f"fingerprint_sha256={fingerprint['sha256']}")

    secret_file = Path("/etc/netbox/deployment/secrets.yml")
    secret_values = parse_secret_values(secret_file) if secret_file.is_file() else []
    private_key_markers = tuple(
        (b"-----" + b"BEGIN " + prefix + b"PRIVATE KEY" + b"-----")
        for prefix in (b"", b"RSA ", b"EC ", b"OPENSSH ")
    )
    leaked_files = []
    for path in evidence.iterdir():
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(marker in data for marker in private_key_markers):
            leaked_files.append(path.name)
        elif secret_values and any(value in data for value in secret_values):
            leaked_files.append(path.name)
    result("AUD-SEC-005", not leaked_files and bool(secret_values), f"evidence_secret_leaks={len(leaked_files)}")

    failed = sum(item["status"] == "FAIL" for item in results)
    warned = sum(item["status"] == "WARN" for item in results)
    summary = {"fail": failed, "warn": warned, "total": len(results), "results": results}
    write(evidence / "audit-summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.chmod(evidence, stat.S_IRWXU)
    print(f"RELEASE_AUDIT_SUMMARY={json.dumps({'fail': failed, 'warn': warned, 'total': len(results)}, sort_keys=True)}")
    print(f"RELEASE_EVIDENCE={evidence}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
