# Troubleshooting

Start with `sudo ./install.sh --preflight` and `sudo ./verify.sh`.

- `CONFLICT`: inspect the unknown NetBox path, invalid managed state or occupied
  port. Never delete the database or marker to bypass safety.
- DNF failure: repair registration or enabled repositories; the installer does
  not change subscription ownership.
- TLS failure: verify certificate names, key pairing and managed permissions.
- Plugin failure: check the installed 0.3.0 package, plugin configuration,
  collected static files and service logs.
- Migration failure: stop and retain the mandatory backup.

```bash
sudo systemctl status postgresql redis netbox netbox-rq nginx firewalld
sudo journalctl -u netbox -u netbox-rq --since today
sudo -u netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check
sudo -u netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py showmigrations --plan
sudo nginx -t
getenforce
```
