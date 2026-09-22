# Upgrade

Checkout a reviewed platform release and run:

```bash
sudo ./upgrade.sh --target-version 4.6.9
```

The command refuses an unpinned target. It checks PostgreSQL, current platform
verification, Subnet Map compatibility and migrations; creates a mandatory
backup; converges; then verifies again. It never selects the newest NetBox.

A future version change requires a reviewed source checksum, compatibility,
migration safety and complete tests in the same Git release.
