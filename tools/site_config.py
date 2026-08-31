#!/usr/bin/env python3
"""Strict parser/validator for the deliberately simple site.yml schema.

This uses only the Python standard library so preflight can run on a clean
RHEL host before PyYAML or Ansible is installed. It accepts mappings, scalar
values, and lists of scalars with two-space indentation.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


def _scalar(text: str) -> Any:
    value = text.strip()
    if not value:
        return {}
    if value.startswith(("'", '"')):
        if len(value) < 2 or value[-1] != value[0]:
            raise ConfigError(f"unterminated quoted scalar: {value}")
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def load_simple_yaml(path: str | Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-2, root)]
    pending_list: tuple[dict[str, Any], str, int] | None = None

    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise ConfigError(f"line {number}: tabs are not allowed")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ConfigError(f"line {number}: indentation must use two-space levels")
        text = raw.strip()

        if text.startswith("- "):
            if pending_list is None or indent != pending_list[2]:
                raise ConfigError(f"line {number}: list item has no parent key")
            parent, key, _ = pending_list
            if not isinstance(parent[key], list):
                parent[key] = []
            parent[key].append(_scalar(text[2:]))
            continue

        if ":" not in text:
            raise ConfigError(f"line {number}: expected key: value")
        key, value_text = text.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            raise ConfigError(f"line {number}: invalid key {key!r}")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack or indent != stack[-1][0] + 2:
            raise ConfigError(f"line {number}: unexpected indentation")
        parent = stack[-1][1]
        if key in parent:
            raise ConfigError(f"line {number}: duplicate key {key!r}")

        if value_text.strip():
            parent[key] = _scalar(value_text)
            pending_list = None
        else:
            parent[key] = {}
            stack.append((indent, parent[key]))
            pending_list = (parent, key, indent + 2)
    return root


def require(config: dict[str, Any], dotted: str, expected_type: type | tuple[type, ...] | None = None) -> Any:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"missing required setting: {dotted}")
        current = current[part]
    if expected_type is not None and not isinstance(current, expected_type):
        raise ConfigError(f"{dotted} has the wrong type")
    return current


def validate(config: dict[str, Any]) -> None:
    required_strings = (
        "deployment.environment",
        "deployment.bundle_version",
        "server.hostname",
        "server.fqdn",
        "server.timezone",
        "expected_network.interface",
        "expected_network.ip_address",
        "expected_network.cidr",
        "expected_network.gateway",
        "packages.source",
        "netbox.version",
        "netbox.admin_username",
        "postgresql.version",
        "postgresql.database",
        "postgresql.username",
        "redis.version",
        "nginx.stream",
        "tls.mode",
        "tls.certificate",
        "tls.private_key",
        "backup.local_path",
    )
    for dotted in required_strings:
        value = require(config, dotted, str)
        if not value:
            raise ConfigError(f"{dotted} must not be empty")

    if require(config, "netbox.version") != "4.6.9":
        raise ConfigError("this bundle supports exactly NetBox 4.6.9")
    if str(require(config, "postgresql.version")) != "16":
        raise ConfigError("this bundle supports exactly PostgreSQL 16")
    if require(config, "packages.source") not in {"bundle", "satellite"}:
        raise ConfigError("packages.source must be bundle or satellite")
    if require(config, "tls.mode") not in {"self_signed_dev", "supplied"}:
        raise ConfigError("tls.mode must be self_signed_dev or supplied")

    address = ipaddress.ip_address(require(config, "expected_network.ip_address"))
    interface = ipaddress.ip_interface(require(config, "expected_network.cidr"))
    if address != interface.ip:
        raise ConfigError("expected_network.ip_address must equal the host in expected_network.cidr")
    ipaddress.ip_address(require(config, "expected_network.gateway"))

    for dotted in ("expected_network.dns", "expected_network.ntp", "netbox.allowed_hosts", "netbox.csrf_trusted_origins"):
        values = require(config, dotted, list)
        if dotted in {"expected_network.dns", "netbox.allowed_hosts"} and not values:
            raise ConfigError(f"{dotted} must not be empty")


def load_and_validate(path: str | Path) -> dict[str, Any]:
    config = load_simple_yaml(path)
    validate(config)
    return config

