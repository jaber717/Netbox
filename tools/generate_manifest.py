#!/usr/bin/env python3
"""Generate deterministic bundle inventory and integrity manifests."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def output(*args: str) -> str:
    if not shutil.which(args[0]):
        return ""
    return subprocess.run(args, text=True, capture_output=True, check=False).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    manifest = root / "manifest"
    manifest.mkdir(parents=True, exist_ok=True)

    rpm_files = sorted((root / "artifacts/rpm-repo").rglob("*.rpm"))
    wheel_files = sorted((root / "artifacts/wheelhouse").glob("*.whl"))

    rpm_manifest = manifest / "RPM-MANIFEST.txt"
    if shutil.which("rpm"):
        rpm_lines = []
        for path in rpm_files:
            nevra = output("rpm", "-qp", "--qf", "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}", str(path))
            if not nevra:
                raise SystemExit(f"unable to inspect RPM metadata: {path}")
            rpm_lines.append(f"{nevra}\t{path.relative_to(root).as_posix()}\tsha256:{digest(path)}")
        rpm_manifest.write_text("\n".join(rpm_lines) + "\n", encoding="utf-8")
    elif not rpm_manifest.is_file() or len(rpm_manifest.read_text(encoding="utf-8").splitlines()) != len(rpm_files):
        raise SystemExit("rpm is unavailable and no matching preserved RPM manifest exists")

    wheel_lines = [
        f"{path.name}\t{path.stat().st_size}\tsha256:{digest(path)}" for path in wheel_files
    ]
    (manifest / "WHEEL-MANIFEST.txt").write_text("\n".join(wheel_lines) + "\n", encoding="utf-8")

    versions_path = manifest / "VERSIONS.yaml"
    python_version = output("python3.12", "--version")
    if python_version or not versions_path.is_file():
        ansible_version = output("ansible-playbook", "--version")
        ansible_version = (
            ansible_version.splitlines()[0]
            if ansible_version
            else "2.14.18 (RHEL package in offline repository)"
        )
        versions = f"""netbox: 4.6.9
deployment_bundle: 1.0.0
rhel_build: 9.6
architecture: {platform.machine()}
python: {python_version.removeprefix('Python ') or '3.12.9'}
postgresql_stream: '16'
redis: '6.2'
nginx_stream: '1.24'
ansible: '{ansible_version}'
source_revision: '{output('git', '-C', str(root), 'rev-parse', 'HEAD') or 'uncommitted-source-tree'}'
build_timestamp_utc: '{dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}'
"""
        versions_path.write_text(versions, encoding="utf-8")

    contains_private_secrets = (root / "config/secrets.yml").is_file()
    classification = "private_release_checkpoint" if contains_private_secrets else "sanitized_distributable"
    bundle = f"""format: NETBOX-RHEL96-OFFLINE
format_version: 1
artifact_classification: {classification}
rpm_count: {len(rpm_files)}
wheel_count: {len(wheel_files)}
rpm_bytes: {sum(path.stat().st_size for path in rpm_files)}
wheel_bytes: {sum(path.stat().st_size for path in wheel_files)}
netbox_source_sha256: '{digest(root / 'artifacts/upstream/netbox-4.6.9.tar.gz')}'
contains_private_secrets_file: {'true' if contains_private_secrets else 'false'}
install_network_required: false
"""
    (manifest / "BUNDLE.yaml").write_text(bundle, encoding="utf-8")

    excluded_roots = {"dist", "build-work", ".git"}
    excluded_files = {
        Path("config/site.yml"),
        Path("config/secrets.yml"),
        Path("manifest/SHA256SUMS"),
    }
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in excluded_roots or relative in excluded_files:
            continue
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        entries.append(f"{digest(path)}  {relative.as_posix()}")
    (manifest / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
