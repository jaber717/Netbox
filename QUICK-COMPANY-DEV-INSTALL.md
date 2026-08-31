# Quick Company DEV Installation

مختصر عملي لتركيب NetBox Offline على Company DEV.

> **مهم:** النسخة المعتمدة للتثبيت حالياً هي Candidate 6 فقط. لا تعدل ملف الـ distributable ولا تعيد ضغطه.
>
> **تنبيه v1.0.0:** لا تشغّل `backup.sh` حالياً إلى أن يتم إصلاح مشكلة PostgreSQL globals backup في hotfix لاحق. هذا لا يمنع تركيب واختبار Company DEV.

## 1) بعد OPSWAT — تحقق من الملف

انسخ إلى RHEL VM:

- `NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz`
- `NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256`

ثم:

```bash
cd /path/to/files
sha256sum -c NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256
```

المطلوب:

```text
NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz: OK
```

إذا لم تظهر `OK`، توقف ولا تكمل.

## 2) فك النسخة

```bash
tar -xzf NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
cd NETBOX-RHEL96-OFFLINE-1.0.0
cat EDIT-ME-FIRST.md
```

## 3) عدّل إعدادات Company DEV

```bash
vi config/site.yml
```

خذ القيم الرسمية من System Team ولا تخمنها:

- Hostname
- FQDN
- Interface
- IP/CIDR
- Gateway
- DNS
- NTP
- TLS
- Backup path

الـ installer يتحقق من الشبكة لكنه لا يغير NIC/IP/Gateway/DNS/NTP.

## 4) راجع بيانات المؤسسة

```bash
vi data/bootstrap/organization.yml
```

راجع أو احذف Home Lab examples قبل Company deployment، خصوصاً:

- Tenants
- Regions
- Sites
- Locations

## 5) أنشئ Secrets على السيرفر نفسه

```bash
sudo python3 tools/initialize_secrets.py --output config/secrets.yml
```

- اختر Initial Admin Password.
- لا ترفع `config/secrets.yml` إلى GitHub.
- لا ترسل محتواه أو تطبعه في logs/evidence.

## 6) شغّل Preflight

```bash
sudo ./bootstrap.sh --preflight
```

القاعدة:

```text
FAIL = 0  -> أكمل
FAIL > 0  -> توقف وصلح السبب
```

## 7) ابدأ التثبيت

فقط إذا كان Preflight بدون Failures:

```bash
sudo ./bootstrap.sh
```

## 8) تحقق من الخدمات

```bash
systemctl is-active netbox netbox-rq nginx postgresql redis
getenforce
```

المطلوب:

```text
active
active
active
active
active
Enforcing
```

## 9) افتح NetBox

```text
https://<COMPANY_FQDN>
```

الدخول الأول:

```text
Username: admin
Password: كلمة المرور التي اخترتها أثناء initialize_secrets.py
```

تحقق من:

- Login
- Dashboard
- HTTPS
- Static files
- API
- عدم وجود Fake Operational Inventory

## 10) اختبر Idempotency

شغّل bootstrap مرة ثانية:

```bash
sudo ./bootstrap.sh
```

المثالي:

```text
changed=0
failed=0
```

والـ taxonomy:

```text
created=0
updated=0
```

## Command Sequence — مختصر جداً

```bash
cd /path/to/files
sha256sum -c NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz.sha256

tar -xzf NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
cd NETBOX-RHEL96-OFFLINE-1.0.0

cat EDIT-ME-FIRST.md
vi config/site.yml
vi data/bootstrap/organization.yml

sudo python3 tools/initialize_secrets.py --output config/secrets.yml
sudo ./bootstrap.sh --preflight

# فقط إذا FAIL=0
sudo ./bootstrap.sh

systemctl is-active netbox netbox-rq nginx postgresql redis
getenforce

# تحقق من الويب ثم اختبر rerun
sudo ./bootstrap.sh
```

## STOP فوراً إذا

- SHA256 لا يطابق.
- Preflight فيه `FAIL`.
- قيم الشبكة غير مؤكدة من System Team.
- Home Lab organization data لم تتم مراجعتها.
- خدمة أساسية ليست `active`.
- SELinux ليس `Enforcing`.
- التثبيت في `bundle` mode حاول الاعتماد على Internet/External repositories.

## Candidate 6 Reference

```text
NETBOX-RHEL96-OFFLINE-1.0.0.tar.gz
SHA256:
7716917084f6d91fdc0a40330bc47bc448a421a091f253ddb89ea14c62c6b3cf
```
