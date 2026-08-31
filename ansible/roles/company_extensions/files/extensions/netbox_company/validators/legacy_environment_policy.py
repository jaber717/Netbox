"""Legacy PROD/DEV/DR policy preserved for review, disabled by default.

Do not enable this module until the company tenant and address ownership model
has been approved. Enablement is controlled exclusively by
features.environment_validators in config/site.yml.
"""

from ipaddress import ip_address, ip_network

from django.core.exceptions import ValidationError
from extras.validators import CustomValidator


ENV_SUPERNETS = {
    "prod": (ip_network("10.10.0.0/16"),),
    "dev": (ip_network("10.20.0.0/16"),),
    "dr": (ip_network("10.30.0.0/16"),),
}


class EnvironmentPrefixValidator(CustomValidator):
    def validate(self, instance, request):
        from ipam.models import Prefix

        errors = []
        tenant = instance.tenant
        if tenant is None:
            raise ValidationError({"tenant": "POLICY VIOLATION — every Prefix requires an environment Tenant."})
        env = tenant.slug.lower()
        approved = ENV_SUPERNETS.get(env)
        candidate = ip_network(str(instance.prefix), strict=False)
        if not approved or not any(candidate.subnet_of(block) for block in approved):
            ranges = ", ".join(str(item) for item in approved or ()) or "no approved supernet"
            errors.append(f"POLICY VIOLATION — {candidate} is outside {tenant.name} approved supernet {ranges}.")

        for other in Prefix.objects.select_related("tenant").exclude(pk=instance.pk):
            if other.tenant_id and other.tenant_id != instance.tenant_id:
                network = ip_network(str(other.prefix), strict=False)
                if candidate.overlaps(network):
                    scope = getattr(other, "scope", None)
                    site = f"; Site: {scope.name}" if scope and scope._meta.label_lower == "dcim.site" else ""
                    errors.append(
                        f"IP OVERLAP CONFLICT — {candidate} overlaps {network}; Owner: {other.tenant.name}{site}."
                    )
        if errors:
            raise ValidationError({"prefix": errors})


class EnvironmentIPAddressValidator(CustomValidator):
    def validate(self, instance, request):
        from ipam.models import Prefix

        if instance.tenant is None:
            raise ValidationError({"tenant": "POLICY VIOLATION — every IP address requires an environment Tenant."})
        host = ip_address(str(instance.address).split("/")[0])
        parents = []
        for prefix in Prefix.objects.select_related("tenant"):
            network = ip_network(str(prefix.prefix), strict=False)
            if host in network:
                parents.append((network.prefixlen, prefix))
        if not parents:
            raise ValidationError({"address": "POLICY VIOLATION — IP address has no parent Prefix."})
        parent = max(parents, key=lambda item: item[0])[1]
        if parent.tenant_id != instance.tenant_id:
            owner = parent.tenant.name if parent.tenant else "unowned"
            raise ValidationError(
                {"tenant": f"IP OVERLAP CONFLICT — IP tenant {instance.tenant.name} does not match parent Prefix owner {owner}."}
            )

