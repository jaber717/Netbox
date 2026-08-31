"""Read-only legacy IPAM audit; policy ranges require review before use."""

from ipaddress import ip_network

from extras.scripts import Script
from ipam.models import Prefix


ENV_SUPERNETS = {
    "prod": ip_network("10.10.0.0/16"),
    "dev": ip_network("10.20.0.0/16"),
    "dr": ip_network("10.30.0.0/16"),
}


class IPAMAuditReport(Script):
    class Meta:
        name = "IPAM Audit Report (Legacy Policy)"
        description = "Read-only ownership/overlap audit; review configured legacy ranges before interpreting results"

    def run(self, data, commit):
        prefixes = list(Prefix.objects.select_related("tenant"))
        violations = {environment: [] for environment in ENV_SUPERNETS}
        seen = {}
        for obj in prefixes:
            network = ip_network(str(obj.prefix))
            if not obj.tenant:
                for environment in violations:
                    violations[environment].append(f"{network}: environment missing")
                continue
            environment = obj.tenant.slug.lower()
            if environment not in ENV_SUPERNETS:
                violations.setdefault(environment, []).append(f"{network}: unknown environment")
                continue
            if not network.subnet_of(ENV_SUPERNETS[environment]):
                violations[environment].append(f"{network}: outside approved supernet")
            key = (str(network), obj.vrf_id)
            if key in seen:
                violations[environment].append(f"{network}: duplicate of ID {seen[key]}")
            seen[key] = obj.pk
        for index, left in enumerate(prefixes):
            if not left.tenant:
                continue
            for right in prefixes[index + 1 :]:
                if right.tenant_id and left.tenant_id != right.tenant_id and ip_network(str(left.prefix)).overlaps(ip_network(str(right.prefix))):
                    violations[left.tenant.slug].append(f"{left.prefix} overlaps {right.prefix} owned by {right.tenant.name}")
                    violations[right.tenant.slug].append(f"{right.prefix} overlaps {left.prefix} owned by {left.tenant.name}")
        lines = ["IPAM HEALTH REPORT", ""]
        clean = True
        for environment in ("prod", "dev", "dr"):
            if violations[environment]:
                clean = False
                lines.append(f"{environment.upper()}: FAIL")
                lines.extend(f"  - {item}" for item in violations[environment])
            else:
                lines.append(f"{environment.upper()}: PASS")
        lines += ["", "OVERALL: CLEAN" if clean else "OVERALL: VIOLATIONS FOUND"]
        report = "\n".join(lines)
        (self.log_success if clean else self.log_failure)(report)
        return report


script_order = (IPAMAuditReport,)

