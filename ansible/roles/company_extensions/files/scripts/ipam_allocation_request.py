"""Legacy write-capable allocation request; not installed unless explicitly enabled."""

from ipaddress import ip_network

from django.core.exceptions import ValidationError
from django.db import transaction
from extras.scripts import BooleanVar, ObjectVar, Script, StringVar
from ipam.models import Prefix
from tenancy.models import Tenant


ENV_SUPERNETS = {"prod": "10.10.0.0/16", "dev": "10.20.0.0/16", "dr": "10.30.0.0/16"}


class IPAMAllocationRequest(Script):
    requested_prefix = StringVar(description="IPv4 prefix in CIDR notation")
    environment = ObjectVar(model=Tenant, query_params={"group": "environments"})
    request_description = StringVar(required=False, label="Description")
    commit_if_valid = BooleanVar(default=False, description="Create the Prefix after all checks pass")

    class Meta:
        name = "IPAM Allocation Request (Legacy Policy)"
        description = "Disabled by default; validates a request against explicitly reviewed legacy policy"

    def run(self, data, commit):
        candidate = ip_network(data["requested_prefix"], strict=True)
        tenant_value = data["environment"]
        tenant = tenant_value if isinstance(tenant_value, Tenant) else Tenant.objects.get(pk=tenant_value)
        approved = ip_network(ENV_SUPERNETS.get(tenant.slug, "0.0.0.0/32"))
        failures = []
        self.log_info(f"Requested: {candidate}")
        self.log_info(f"Environment: {tenant.name}")
        if not candidate.subnet_of(approved):
            message = f"FAIL — approved supernet: {candidate} is outside {tenant.name} {approved}"
            failures.append(message)
            self.log_failure(message)
        for other in Prefix.objects.select_related("tenant"):
            if other.tenant_id and other.tenant_id != tenant.id and candidate.overlaps(ip_network(str(other.prefix))):
                scope = getattr(other, "scope", None)
                site = scope.name if scope and scope._meta.label_lower == "dcim.site" else "not scoped to a site"
                message = f"FAIL — IP OVERLAP CONFLICT: Overlaps {other.prefix}; Owner: {other.tenant.name}; Site: {site}"
                failures.append(message)
                self.log_failure(message)
        if failures:
            self.log_failure("VERDICT: REJECT")
            return "\n".join(failures + ["VERDICT: REJECT"])
        self.log_success("VERDICT: APPROVE")
        if data["commit_if_valid"] and commit:
            try:
                with transaction.atomic():
                    obj = Prefix(
                        prefix=str(candidate),
                        tenant=tenant,
                        status="active",
                        description=data.get("request_description") or "Approved by IPAM Allocation Request",
                    )
                    obj.full_clean()
                    obj.save()
                self.log_success(f"Created {obj.prefix}")
            except ValidationError as exc:
                self.log_failure(f"Validation stopped commit: {exc}")
                raise
        return "VERDICT: APPROVE"


script_order = (IPAMAllocationRequest,)

