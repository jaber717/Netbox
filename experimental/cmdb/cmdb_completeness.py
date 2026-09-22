"""Recovered prototype Custom Script; not installed by Production v1."""
from datetime import timedelta
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from dcim.models import Device
from extras.scripts import BooleanVar, Script
from tenancy.models import ContactAssignment

PASSIVE_ROLES = {"patch-panel", "odf", "pdu"}
SCORED_FIELDS = ("tenant", "role", "serial", "asset_tag", "primary_ip", "criticality",
                 "data_source", "lifecycle_state", "support_expiry", "owner", "last_seen")

def has_owner(device):
    for obj in [device, *[value for value in (device.site, device.tenant, device.role) if value]]:
        object_type = ContentType.objects.get_for_model(obj)
        if ContactAssignment.objects.filter(object_type=object_type, object_id=obj.pk).exists():
            return True
    return False

def missing_fields(device, stale_days=90):
    custom = device.custom_field_data or {}; missing = []
    for present, name in ((device.tenant_id, "tenant"), (device.role_id, "role"), (device.serial, "serial"),
                          (device.asset_tag, "asset_tag"), (device.primary_ip4_id or device.primary_ip6_id, "primary_ip")):
        if not present: missing.append(name)
    for name in ("criticality", "data_source", "lifecycle_state", "support_expiry", "last_seen"):
        if not custom.get(name): missing.append(name)
    if not has_owner(device): missing.append("owner")
    observed = custom.get("last_seen"); stale = False
    if observed:
        if isinstance(observed, str): observed = timezone.datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if timezone.is_naive(observed): observed = timezone.make_aware(observed, timezone.utc)
        stale = observed < timezone.now() - timedelta(days=stale_days)
    return missing, stale

def build_report(include_passive=False, stale_days=90):
    devices = Device.objects.select_related("tenant", "role", "site").filter(status="active")
    if not include_passive: devices = devices.exclude(role__slug__in=PASSIVE_ROLES)
    devices = list(devices); counts = {field: 0 for field in SCORED_FIELDS}; rows = []; complete = stale_count = 0
    for device in devices:
        missing, stale = missing_fields(device, stale_days)
        for field in missing: counts[field] += 1
        complete += len(SCORED_FIELDS) - len(missing); stale_count += int(stale); rows.append((device.name, missing, stale))
    total = len(devices) * len(SCORED_FIELDS)
    return {"devices": len(devices), "percent": 100.0 if not total else round(100 * complete / total, 2),
            "missing": counts, "stale": stale_count, "rows": rows}

class CMDBCompletenessReport(Script):
    include_passive = BooleanVar(description="Include passive infrastructure.", default=False, required=False)
    class Meta:
        name = "CMDB Completeness Report"
        description = "Scores identity, ownership, lifecycle and provenance."
        commit_default = False
        scheduling_enabled = True
    def run(self, data, commit):
        report = build_report(data.get("include_passive", False))
        self.log_success(f"Devices: {report['devices']}")
        self.log_success(f"CMDB completeness: {report['percent']}%")
        for field, count in report["missing"].items():
            if count: self.log_warning(f"{count} missing {field.replace('_', ' ')}")
        if report["stale"]: self.log_warning(f"{report['stale']} stale >90 days")
        return f"Devices: {report['percent']}% complete; stale >90 days: {report['stale']}"
