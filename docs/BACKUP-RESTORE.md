# Backup and restore

`sudo ./backup.sh` creates a mode-0600 archive and SHA-256 sidecar. It contains
the PostgreSQL custom dump, media, managed non-secret configuration, service
files, release state, product tooling and locally managed TLS certificate/key.
Application/database secrets remain a separate root-only recovery artifact.

Non-destructive validation restores only into a disposable scratch database:

```bash
sudo /usr/local/sbin/netbox-restore-verify --archive /path/netbox-backup-*.tar.gz
```

Live restore requires explicit confirmation:

```bash
sudo ./restore.sh --archive /path/netbox-backup-*.tar.gz --confirm NETBOX-RESTORE
```

Installation and upgrade never invoke restore automatically.
