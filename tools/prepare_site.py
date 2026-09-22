#!/usr/bin/env python3
"""Create a local, non-secret site.yml from safe host facts."""
from __future__ import annotations

import argparse
import socket
from pathlib import Path


def primary_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("198.51.100.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="config/site.yml.example")
    parser.add_argument("--output", default="config/site.yml")
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        print(f"Site configuration already exists at {target}; no values changed.")
        return 0
    hostname = socket.gethostname().split(".", 1)[0]
    fqdn = socket.getfqdn() or hostname
    if "." not in fqdn:
        fqdn = hostname
    rendered = Path(args.template).read_text(encoding="utf-8")
    for token, value in {
        "__HOSTNAME__": hostname,
        "__FQDN__": fqdn,
        "__PRIMARY_IP__": primary_ip(),
    }.items():
        rendered = rendered.replace(token, value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    print(f"Created {target}; review it before production use if host facts are temporary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
