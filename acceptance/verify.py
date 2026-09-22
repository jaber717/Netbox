#!/usr/bin/env python3
"""Non-destructive operational verification for the connected NetBox platform."""
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from pathlib import Path

passed = failed = 0

def run(*argv):
    return subprocess.run(argv, text=True, capture_output=True, check=False)

def check(label, condition, detail=""):
    global passed, failed
    passed += int(bool(condition)); failed += int(not condition)
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))

def active(service):
    return run("systemctl", "is-active", "--quiet", service).returncode == 0

def django_state():
    script = r'''
import importlib.metadata, json
from django.conf import settings
from django.urls import resolve, reverse
print("VERIFY_JSON=" + json.dumps({
  "version": settings.VERSION,
  "plugins": list(settings.PLUGINS),
  "validators": settings.CUSTOM_VALIDATORS,
  "subnet_map_version": importlib.metadata.version("netbox-subnet-map"),
  "subnet_map_route": resolve(reverse("ipam:prefix_subnet_map", kwargs={"pk": 1})).url_name,
}, sort_keys=True))
'''
    result = run("runuser", "-u", "netbox", "--", "/opt/netbox/venv/bin/python", "/opt/netbox/netbox/manage.py", "shell", "-c", script)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    line = next(line for line in result.stdout.splitlines() if line.startswith("VERIFY_JSON="))
    return json.loads(line.split("=", 1)[1])

def main():
    release = platform.freedesktop_os_release()
    check("RHEL 9.x", release.get("ID") == "rhel" and bool(re.fullmatch(r"9\.[0-9]+", release.get("VERSION_ID", ""))), release.get("PRETTY_NAME", "unknown"))
    check("Architecture x86_64", platform.machine() == "x86_64", platform.machine())
    check("SELinux Enforcing", run("getenforce").stdout.strip() == "Enforcing")
    check("firewalld active", active("firewalld"))
    for service in ("postgresql", "redis", "netbox", "netbox-rq", "nginx"):
        check(f"{service} active", active(service))
    migrations = run("runuser", "-u", "netbox", "--", "/opt/netbox/venv/bin/python", "/opt/netbox/netbox/manage.py", "showmigrations", "--plan")
    check("Migrations current", migrations.returncode == 0 and "[ ]" not in migrations.stdout)
    check("Static assets present", Path("/var/www/netbox/static/netbox.css").is_file())
    check("nginx configuration", run("nginx", "-t").returncode == 0)
    try:
        state = django_state()
    except Exception as exc:
        check("Django state", False, type(exc).__name__); state = {}
    else:
        check("NetBox 4.6.9", state["version"] == "4.6.9", state["version"])
        check("Subnet Map loaded", "netbox_subnet_map" in state["plugins"], str(state["plugins"]))
        check("Subnet Map 0.3.0", state["subnet_map_version"] == "0.3.0", state["subnet_map_version"])
        check("Subnet Map route", state["subnet_map_route"] == "prefix_subnet_map")
        check("CMDB disabled", not any("cmdb" in name for name in state["plugins"]))
    release_path = Path("/etc/netbox-platform/release.json")
    try: managed = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): managed = {}
    check("Release state", managed.get("managed_by") == "netbox-platform" and managed.get("netbox_version") == "4.6.9")
    site = Path("/etc/netbox/deployment/site.yml").read_text(encoding="utf-8") if Path("/etc/netbox/deployment/site.yml").is_file() else ""
    fqdn = re.search(r"^  fqdn: (.+)$", site, re.MULTILINE); cert = re.search(r"^  certificate: (.+)$", site, re.MULTILINE)
    if fqdn and cert:
        common = ("curl", "--fail", "--silent", "--show-error", "--cacert", cert.group(1), "--resolve", f"{fqdn.group(1)}:443:127.0.0.1")
        api = run(*common, f"https://{fqdn.group(1)}/api/")
        check("HTTPS API", api.returncode == 0)
        login = run(*common, f"https://{fqdn.group(1)}/login/")
        check("Login page", login.returncode == 0 and "csrfmiddlewaretoken" in login.stdout)
    else:
        check("HTTPS configuration", False, "persisted site configuration unavailable")
    sockets = run("ss", "-H", "-lnt").stdout.splitlines(); exposed = []
    for line in sockets:
        endpoint = line.split()[3] if len(line.split()) > 3 else ""
        if any(endpoint.endswith(f":{port}") for port in (5432, 6379, 8001)) and not endpoint.startswith(("127.0.0.1:", "[::1]:")):
            exposed.append(endpoint)
    check("Database/cache/Gunicorn loopback-only", not exposed, str(exposed))
    print(f"\nVERIFY: PASS={passed} FAIL={failed} TOTAL={passed + failed}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
