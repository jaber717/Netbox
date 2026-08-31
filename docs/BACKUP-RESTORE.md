# Backup and Restore

## Backup

Run:

```bash
sudo ./backup.sh
# or
sudo /usr/local/sbin/netbox-backup
```

The ordinary backup contains a PostgreSQL custom-format dump, PostgreSQL
globals, non-secret deployment inputs, media, company extensions, nginx
configuration, and NetBox systemd units. Archives and their SHA256 sidecars are
mode 0600. It deliberately excludes `config/secrets.yml`, rendered NetBox
database/Redis credentials, `SECRET_KEY`, `API_TOKEN_PEPPERS`, and private-key
material. A daily systemd timer is enabled. Retention and the optional off-box
rsync target come from `config/site.yml`.

Private deployment secrets are a separate recovery artifact. Preserve them in
company-approved secret/password management. Backup metadata stores only
generation fingerprints. The peppers fingerprint uses a canonical sequence
sorted by numeric pepper ID; actual values are never written. Losing matching
peppers affects existing v2 API-token verification. Changing `SECRET_KEY`
invalidates existing sessions but does not destroy stored NetBox data.

Git is not a database or media backup. Copy backups off the VM under the
company's approved protection and retention controls.

## Restore safety

Restore replaces the NetBox database and persistent files. Verify the target,
archive, checksum, change window, and off-box recovery copy first.

```bash
sudo ./restore.sh \
  --archive /var/backups/netbox/netbox-backup-YYYYMMDDTHHMMSSZ.tar.gz \
  --confirm NETBOX-RESTORE
```

The guard requires the exact confirmation string and an adjacent checksum. The
script validates structure before stopping services, recreates only the NetBox
database, restores persistent files, reapplies SELinux contexts, restarts the
stack, and runs acceptance.

PostgreSQL globals are retained as recovery evidence but are not blindly applied
by the automated restore because doing so could alter unrelated cluster roles.
The deployment bootstrap must have created the expected NetBox role first.

Test restore procedures periodically on an isolated VM. A successful backup is
not proof of recoverability until restore is tested.

The release supplies a non-destructive proof which restores into a uniquely
named scratch database, validates it, and removes it:

```bash
sudo netbox-restore-verify \
  --archive /var/backups/netbox/netbox-backup-YYYYMMDDTHHMMSSZ.tar.gz
```

A secret-generation fingerprint mismatch produces a warning before a real
restore so operators can recover the matching private generation first.
