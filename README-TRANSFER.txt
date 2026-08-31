NETBOX RHEL 9.6 OFFLINE TRANSFER

1. Send NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz through OPSWAT.
2. Copy the approved, unchanged archive and its .sha256 sidecar to the RHEL VM.
3. Run: sha256sum -c NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256
4. Extract the archive.
5. Read EDIT-ME-FIRST.md and edit config/site.yml.
6. The distributable contains no config/secrets.yml. Generate it privately on
   the target without printing values:
   sudo python3 tools/initialize_secrets.py --output config/secrets.yml
   Keep the resulting file root-only mode 0600 and recover its values through
   company-approved secret/password management separate from the release.
7. Run: sudo ./bootstrap.sh --preflight
8. If and only if preflight has zero failures, run: sudo ./bootstrap.sh

The target install does not require Internet, GitHub, PyPI, Red Hat CDN, EPEL,
Remi, containers, or Codex. Networking is validated but never reconfigured.
This OPSWAT artifact is SANITIZED and contains no live deployment secrets.
