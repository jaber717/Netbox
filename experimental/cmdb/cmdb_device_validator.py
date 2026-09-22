"""Recovered prototype; not installed by Production v1."""
from django.core.exceptions import ValidationError
from extras.validators import CustomValidator

PASSIVE_ROLES = {"patch-panel", "odf", "pdu"}

class ActiveCMDBDeviceValidator(CustomValidator):
    def validate(self, instance, request):
        role_slug = instance.role.slug if instance.role_id else ""
        if instance.status != "active" or role_slug in PASSIVE_ROLES:
            return
        errors = {}
        if not instance.tenant_id: errors["tenant"] = "CMDB POLICY — active managed devices require a Tenant."
        if not instance.role_id: errors["role"] = "CMDB POLICY — active managed devices require a Device Role."
        if not instance.serial: errors["serial"] = "CMDB POLICY — active managed devices require a serial number."
        custom = instance.custom_field_data or {}
        missing = [label for key, label in (("criticality", "Criticality"), ("data_source", "Data Source")) if not custom.get(key)]
        if missing: errors["custom_fields"] = "CMDB POLICY — active managed devices require " + " and ".join(missing) + "."
        if errors: raise ValidationError(errors)
