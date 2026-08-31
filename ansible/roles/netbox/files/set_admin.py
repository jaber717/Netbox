import os

from users.models import User

username = os.environ["NETBOX_INITIAL_ADMIN_USERNAME"]
password = os.environ["NETBOX_INITIAL_ADMIN_PASSWORD"]
user, created = User.objects.get_or_create(username=username)
changed = created
for field in ("is_active", "is_superuser"):
    if not getattr(user, field):
        setattr(user, field, True)
        changed = True
if not user.check_password(password):
    user.set_password(password)
    changed = True
if changed:
    user.full_clean(exclude=["password"])
    user.save()
print(f"ADMIN_CHANGED={1 if changed else 0}")
