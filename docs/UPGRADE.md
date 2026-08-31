# Upgrade Strategy

Upgrades use a newly built and independently validated offline bundle. Never
download a NetBox release or Python dependency on the target.

Before approving a new bundle:

1. Check the NetBox release notes and supported Python/PostgreSQL/Redis versions.
2. Build on the exact supported RHEL minor and architecture.
3. Recreate RPM/module and wheel closures.
4. Run wheelhouse and DNF install-root rehearsals offline.
5. Restore a production-like backup to an isolated VM and test the full upgrade.
6. Record the compatibility decision and rollback procedure.

On the target, run the guarded wrapper from the current bundle:

```bash
sudo ./upgrade.sh --bundle /approved/path/NETBOX-RHEL96-OFFLINE-<new-version>
```

The wrapper verifies the existing managed install, runs a pre-upgrade backup,
runs the new bundle's preflight, invokes its bootstrap, and runs acceptance.
The new bundle owns its versioned release directory and stable symlink.

Database migrations are not transactionally reversible across an application
rollback. If a migration is incompatible, restore the pre-upgrade PostgreSQL
backup and matching configuration/application release. Merely changing the
`/opt/netbox` symlink is not a safe database rollback.
