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
    if value == "[]":
        return []
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
        "platform.version",
        "deployment.environment",
        "deployment.installation_mode",
        "server.hostname",
        "server.fqdn",
        "server.primary_ip",
        "server.timezone",
        "packages.source",
        "netbox.version",
        "netbox.source_sha256",
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
    if require(config, "packages.source") not in {"bundle", "connected"}:
        raise ConfigError("packages.source must be connected or bundle")
    if require(config, "deployment.installation_mode") not in {"connected", "offline"}:
        raise ConfigError("deployment.installation_mode must be connected or offline")
    if require(config, "tls.mode") not in {"self_signed", "supplied"}:
        raise ConfigError("tls.mode must be self_signed or supplied")
    if not re.fullmatch(r"[0-9a-f]{64}", require(config, "netbox.source_sha256")):
        raise ConfigError("netbox.source_sha256 must be a lowercase SHA-256 digest")
    ipaddress.ip_address(require(config, "server.primary_ip"))

    for dotted in ("netbox.allowed_hosts", "netbox.csrf_trusted_origins"):
        values = require(config, dotted, list)
        if dotted == "netbox.allowed_hosts" and not values:
            raise ConfigError(f"{dotted} must not be empty")

    for dotted in (
        "features.generic_foundation", "features.environment_validators",
        "features.ipam_audit_report", "features.ipam_allocation_request",
        "features.subnet_map", "features.cmdb",
    ):
        require(config, dotted, bool)
    if require(config, "features.cmdb"):
        raise ConfigError("CMDB is not production-ready in this release and cannot be enabled")


def load_and_validate(path: str | Path) -> dict[str, Any]:
    config = load_simple_yaml(path)
    validate(config)
    return config

