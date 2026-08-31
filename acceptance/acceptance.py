#!/usr/bin/env python3
"""Post-install acceptance suite for the native RHEL 9.6 deployment."""

from __future__ import annotations

import json
import os
import platform
import re
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path


passed = 0
failed = 0
warned = 0
skipped = 0


def command(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, check=False)


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    suffix = f" — {detail}" if detail else ""
    if condition:
        passed += 1
        print(f"[PASS] {label}{suffix}")
    else:
        failed += 1
        print(f"[FAIL] {label}{suffix}")


def warning(label: str, detail: str) -> None:
    global warned
    warned += 1
    print(f"[WARN] {label} — {detail}")


def active(name: str) -> bool:
    return command("systemctl", "is-active", "--quiet", name).returncode == 0


def django_state() -> dict:
    script = r'''
import json
from circuits.models import Circuit, CircuitTermination, CircuitType, Provider
from dcim.models import Cable, ConsolePortTemplate, ConsoleServerPortTemplate, Device, DeviceRole, DeviceType, FrontPortTemplate, InterfaceTemplate, Location, Manufacturer, Platform, PortTemplateMapping, Rack, RearPortTemplate, Region, Site
from django.conf import settings
from extras.models import CustomField, CustomFieldChoiceSet
from ipam.models import Aggregate, IPAddress, Prefix, RIR, Role, VLAN
from tenancy.models import Tenant, TenantGroup
from users.models import User
print("ACCEPTANCE_JSON=" + json.dumps({
  "version": settings.VERSION,
  "foundation": {
    "manufacturers": Manufacturer.objects.count(), "device_types": DeviceType.objects.count(),
    "device_roles": DeviceRole.objects.count(), "platforms": Platform.objects.count(),
    "tenant_groups": TenantGroup.objects.count(), "tenants": Tenant.objects.count(),
    "regions": Region.objects.count(), "sites": Site.objects.count(), "locations": Location.objects.count(),
    "ipam_roles": Role.objects.count(), "rirs": RIR.objects.count(),
    "circuit_types": CircuitType.objects.count(), "providers": Provider.objects.count(),
    "choice_sets": CustomFieldChoiceSet.objects.count(), "custom_fields": CustomField.objects.count(),
    "interface_templates": InterfaceTemplate.objects.count(), "console_port_templates": ConsolePortTemplate.objects.count(),
    "console_server_port_templates": ConsoleServerPortTemplate.objects.count(),
    "front_port_templates": FrontPortTemplate.objects.count(), "rear_port_templates": RearPortTemplate.objects.count(),
    "port_template_mappings": PortTemplateMapping.objects.count(),
  },
  "operational": {
    "racks": Rack.objects.count(), "devices": Device.objects.count(), "cables": Cable.objects.count(),
    "prefixes": Prefix.objects.count(), "ip_addresses": IPAddress.objects.count(), "vlans": VLAN.objects.count(),
    "aggregates": Aggregate.objects.count(), "circuits": Circuit.objects.count(),
    "circuit_terminations": CircuitTermination.objects.count(),
  },
  "admin_ok": User.objects.filter(username="admin", is_active=True, is_superuser=True).exists(),
  "custom_validators": settings.CUSTOM_VALIDATORS,
}, sort_keys=True))
'''
    result = command(
        "runuser", "-u", "netbox", "--", "/opt/netbox/venv/bin/python",
        "/opt/netbox/netbox/manage.py", "shell", "-c", script,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    line = next(line for line in result.stdout.splitlines() if line.startswith("ACCEPTANCE_JSON="))
    return json.loads(line.split("=", 1)[1])


def main() -> int:
    release = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip().strip('"')
    check("RHEL 9.6", release.get("ID") == "rhel" and release.get("VERSION_ID") == "9.6")
    check("Architecture x86_64", platform.machine() == "x86_64", platform.machine())
    check("SELinux Enforcing", command("getenforce").stdout.strip() == "Enforcing")

    python_version = command("/opt/netbox/venv/bin/python", "--version").stdout.strip()
    check("Python 3.12", python_version.startswith("Python 3.12"), python_version)
    postgresql_version = command("psql", "--version").stdout
    check("PostgreSQL 16", bool(re.search(r"\b16(?:\.|\b)", postgresql_version)), postgresql_version.strip())
    redis_version = command("redis-server", "--version").stdout
    check("Redis 6.2", "v=6.2" in redis_version, redis_version.strip())
    nginx_version = command("nginx", "-v").stderr
    check("nginx 1.24", "nginx/1.24" in nginx_version, nginx_version.strip())

    for service in ("postgresql", "redis", "netbox", "netbox-rq", "nginx", "firewalld"):
        check(f"{service} service active", active(service))

    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen("https://127.0.0.1/api/", context=context, timeout=10) as response:
            api_ok = response.status == 200 and "application/json" in response.headers.get("Content-Type", "")
    except Exception as exc:
        api_ok = False
        api_detail = str(exc)
    else:
        api_detail = "HTTP 200"
    check("NetBox API over HTTPS", api_ok, api_detail)

    try:
        with urllib.request.urlopen("https://127.0.0.1/static/netbox.css", context=context, timeout=10) as response:
            static_ok = response.status == 200 and len(response.read(128)) > 0
    except Exception as exc:
        static_ok = False
        static_detail = str(exc)
    else:
        static_detail = "HTTP 200"
    check("Static files served", static_ok, static_detail)

    migrations = command(
        "runuser", "-u", "netbox", "--", "/opt/netbox/venv/bin/python",
        "/opt/netbox/netbox/manage.py", "showmigrations", "--plan",
    )
    check("Database migrations current", migrations.returncode == 0 and "[ ]" not in migrations.stdout)

    state = django_state()
    check("NetBox 4.6.9", state["version"] == "4.6.9", state["version"])
    expected_foundation = {
        "manufacturers": 8, "device_types": 11, "device_roles": 10, "platforms": 4,
        "tenant_groups": 1, "tenants": 3, "regions": 3, "sites": 3, "locations": 4,
        "ipam_roles": 10, "rirs": 1, "circuit_types": 3, "providers": 2,
        "choice_sets": 1, "custom_fields": 1, "interface_templates": 177,
        "console_port_templates": 5, "console_server_port_templates": 48,
        "front_port_templates": 168, "rear_port_templates": 168, "port_template_mappings": 168,
    }
    check("Bootstrap taxonomy exact", state["foundation"] == expected_foundation, json.dumps(state["foundation"], sort_keys=True))
    check("No fake operational inventory", all(value == 0 for value in state["operational"].values()), json.dumps(state["operational"], sort_keys=True))
    check("Initial admin exists", state["admin_ok"])
    check("Environment validators disabled", state["custom_validators"] == {}, str(state["custom_validators"]))
    check("Validator source imports", command("runuser", "-u", "netbox", "--", "/opt/netbox/venv/bin/python", "/opt/netbox/netbox/manage.py", "shell", "-c", "import netbox_company.validators.legacy_environment_policy").returncode == 0)
    check("IPAM Audit Report installed", Path("/var/lib/netbox/scripts/ipam_audit_report.py").is_file())
    check("IPAM Allocation Request disabled", not Path("/var/lib/netbox/scripts/ipam_allocation_request.py").exists())

    sockets = command("ss", "-H", "-lnt").stdout.splitlines()
    external = {5432: [], 6379: [], 8001: []}
    for line in sockets:
        parts = line.split()
        endpoint = parts[3] if len(parts) > 3 else ""
        for port in external:
            if endpoint.endswith(f":{port}") and not endpoint.startswith(("127.0.0.1:", "[::1]:")):
                external[port].append(endpoint)
    check("PostgreSQL not externally exposed", not external[5432], str(external[5432]))
    check("Redis not externally exposed", not external[6379], str(external[6379]))
    check("Gunicorn not externally exposed", not external[8001], str(external[8001]))

    firewall_443 = command("firewall-cmd", "--permanent", "--query-port=443/tcp").returncode == 0
    forbidden_firewall = any(command("firewall-cmd", "--permanent", f"--query-port={port}/tcp").returncode == 0 for port in (5432, 6379, 8001))
    check("Firewalld HTTPS allowed", firewall_443)
    check("Firewalld internal ports closed", not forbidden_firewall)
    check("No legacy housekeeping unit", not Path("/etc/systemd/system/netbox-housekeeping.service").exists() and not Path("/etc/systemd/system/netbox-housekeeping.timer").exists())

    backup = command("/usr/local/sbin/netbox-backup")
    check("Backup command succeeds", backup.returncode == 0, backup.stdout.strip().splitlines()[-1] if backup.stdout.strip() else backup.stderr.strip())
    backup_path = ""
    for line in backup.stdout.splitlines():
        if line.startswith("Backup created: "):
            backup_path = line.split(": ", 1)[1]
    restore_verify = command("/usr/local/sbin/netbox-restore-verify", "--archive", backup_path) if backup_path else None
    check(
        "Scratch database restore verification",
        bool(restore_verify and restore_verify.returncode == 0),
        (restore_verify.stdout.strip().splitlines()[-1] if restore_verify and restore_verify.stdout.strip() else (restore_verify.stderr.strip() if restore_verify else "backup path unavailable")),
    )

    taxonomy = command(
        "runuser", "-u", "netbox", "--", "/bin/bash", "-c",
        "/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell < /opt/netbox-company/bootstrap_taxonomy.py",
    )
    check("Bootstrap taxonomy idempotent", taxonomy.returncode == 0 and "created=0 updated=0" in taxonomy.stdout, taxonomy.stdout.strip().splitlines()[-1] if taxonomy.stdout.strip() else taxonomy.stderr.strip())

    cert = command("openssl", "x509", "-in", "/etc/pki/tls/certs/netbox.crt", "-noout", "-issuer", "-subject")
    lines = cert.stdout.splitlines()
    if len(lines) >= 2 and lines[0].replace("issuer=", "") == lines[1].replace("subject=", ""):
        warning("TLS certificate", "self-signed development certificate is active")

    summary = {"pass": passed, "fail": failed, "skip": skipped, "warn": warned, "total": passed + failed + skipped}
    print(f"\nACCEPTANCE_SUMMARY={json.dumps(summary, sort_keys=True)}")
    print(f"ACCEPTANCE: PASS={passed} FAIL={failed} SKIP={skipped} TOTAL={summary['total']} WARN={warned}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
