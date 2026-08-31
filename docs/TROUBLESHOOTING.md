# Troubleshooting

## Preflight fails

Read the expected and detected values in the `FAIL` line. Correct
`config/site.yml` only if the declaration is wrong. If the VM is wrong, stop and
ask the system team to correct networking/time/hostname. The installer must not
reconfigure those settings.

For an integrity failure, do not bypass the manifest. Re-copy the approved
unchanged bundle or rebuild it through the controlled build process.

## Service health

```bash
sudo systemctl status netbox netbox-rq nginx postgresql redis --no-pager
sudo journalctl -u netbox -u netbox-rq -u nginx -n 100 --no-pager
sudo nginx -t
sudo /usr/local/sbin/netbox-acceptance
```

Do not paste private configuration or unredacted Redis/PostgreSQL credentials
into tickets or chat.

## SELinux

Never use `setenforce 0`. Inspect recent AVCs and current labels:

```bash
sudo ausearch -m AVC -ts recent
sudo restorecon -RFv /var/www/netbox/static /var/lib/netbox/media
```

Fix the Ansible role with a standard boolean/type or a narrowly justified policy.

## API/static errors

```bash
curl -kI https://127.0.0.1/api/
curl -kI https://127.0.0.1/static/netbox.css
sudo ss -lntp
```

Expected listeners are nginx on public 80/443 and internal services on
127.0.0.1 only.

## Offline DNF

In bundle mode, verify both files exist:

- `artifacts/rpm-repo/base/repodata/repomd.xml`
- `artifacts/rpm-repo/modules/repodata/repomd.xml`

Do not enable Internet repositories as a workaround. Missing closure is a bundle
build defect and must be corrected on the registered build VM.
