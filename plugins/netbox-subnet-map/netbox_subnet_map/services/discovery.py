"""Permission-aware search, free-space and conflict analysis on NetBox data."""
from __future__ import annotations

import ipaddress

import netaddr
from django.db.models.functions import Cast

from ipam.fields import IPAddressField
from ipam.lookups import Host
from ipam.models import IPAddress, IPRange, Prefix, VRF


HOST_ADDRESS = Cast(Host("address"), output_field=IPAddressField())
FILTER_KEYS = (
    "q", "address", "prefix", "vrf", "tenant", "status", "device",
    "interface", "vm", "dns_name", "vlan", "site",
)


def _contains(value, needle):
    return needle.casefold() in str(value or "").casefold()


def _address_matches(host, expression):
    if not expression:
        return True
    try:
        if "/" in expression:
            return ipaddress.ip_address(host) in ipaddress.ip_network(expression, strict=False)
        return ipaddress.ip_address(host) == ipaddress.ip_address(expression)
    except ValueError:
        return _contains(host, expression)


def filter_subnet_map(subnet_map, params):
    """Filter only the permission-trimmed read model; never query hidden objects."""
    filters = {key: str(params.get(key, "")).strip() for key in FILTER_KEYS}

    def matches(record):
        ips = record["ip_objects"]
        assignments = [item["assignment"] for item in ips]
        checks = {
            "address": _address_matches(record["address_host"], filters["address"]),
            "prefix": _contains(subnet_map["prefix"]["cidr"], filters["prefix"]),
            "vrf": _contains(subnet_map["prefix"]["vrf"], filters["vrf"]),
            "tenant": any(_contains(item["tenant"], filters["tenant"]) for item in ips)
                      or _contains(subnet_map["prefix"]["tenant"], filters["tenant"]),
            "status": any(_contains(item["status"], filters["status"]) for item in ips),
            "device": any(item["type"] == "dcim.Interface" and _contains(item["parent"], filters["device"]) for item in assignments),
            "interface": any(_contains(item["interface"], filters["interface"]) for item in assignments),
            "vm": any(item["type"] == "virtualization.VMInterface" and _contains(item["parent"], filters["vm"]) for item in assignments),
            "dns_name": any(_contains(item["dns_name"], filters["dns_name"]) for item in ips),
            "vlan": _contains(subnet_map["prefix"]["vlan"], filters["vlan"]),
            "site": any(_contains(item["site"], filters["site"]) for item in assignments),
        }
        if any(filters[key] and not checks[key] for key in checks):
            return False
        if filters["q"]:
            haystack = [record["address_host"], *record["derived_states"], subnet_map["prefix"]["cidr"],
                        subnet_map["prefix"]["vrf"], subnet_map["prefix"]["tenant"], subnet_map["prefix"]["vlan"]]
            for item in ips:
                haystack.extend((item["address"], item["status"], item["tenant"], item["dns_name"], item["description"]))
                haystack.extend(str(value) for value in item["assignment"].values())
            return any(_contains(value, filters["q"]) for value in haystack)
        return True

    if any(filters.values()):
        subnet_map["records"] = [record for record in subnet_map["records"] if matches(record)]
    subnet_map["filters"] = filters
    subnet_map["filter_active"] = any(filters.values())
    subnet_map["filtered_count"] = len(subnet_map["records"])
    return subnet_map


class FreeSpaceFinder:
    """Fail-closed free-space analysis within one Prefix and its exact VRF."""

    def __init__(self, prefix, user, *, limit=32):
        self.prefix = prefix
        self.user = user
        self.limit = max(1, min(int(limit), 256))
        network = netaddr.IPNetwork(prefix.prefix)
        first, last = prefix.usable_ip_bounds
        self.network = network
        self.bounds = netaddr.IPSet([netaddr.IPRange(first, last)])
        self.ips = IPAddress.objects.filter(
            vrf_id=prefix.vrf_id,
            address__host_between=(netaddr.IPAddress(network.first), netaddr.IPAddress(network.last)),
        )
        self.ranges = IPRange.objects.filter(
            vrf_id=prefix.vrf_id,
            start_address__host__inet__lte=netaddr.IPAddress(network.last),
            end_address__host__inet__gte=netaddr.IPAddress(network.first),
        )
        self.children = Prefix.objects.filter(
            vrf_id=prefix.vrf_id, prefix__net_contained=str(prefix.prefix)
        ).exclude(pk=prefix.pk)

    @staticmethod
    def _complete(queryset, visible):
        return not queryset.exclude(pk__in=visible.values("pk")).exists()

    def _visible(self):
        visible = tuple(queryset.restrict(self.user, "view") for queryset in (self.ips, self.ranges, self.children))
        complete = all(self._complete(queryset, allowed) for queryset, allowed in zip((self.ips, self.ranges, self.children), visible))
        if self.prefix.vrf_id and not VRF.objects.filter(pk=self.prefix.vrf_id).restrict(self.user, "view").exists():
            complete = False
        return (*visible, complete)

    def summary(self, requested_prefix_length=None):
        ips, ranges, children, complete = self._visible()
        if not complete or self.prefix.status == "container" or self.prefix.mark_utilized:
            return {"known": False, "reason": "Visibility is incomplete or this Prefix is not allocatable.",
                    "next_ip": None, "free_ranges": [], "child_candidate": None, "requested_prefix_length": requested_prefix_length}
        occupied = netaddr.IPSet()
        for host in ips.annotate(host=HOST_ADDRESS).values_list("host", flat=True):
            occupied.add(netaddr.IPAddress(host))
        for item in ranges:
            occupied.add(netaddr.IPRange(item.start_address.ip, item.end_address.ip))
        for child in children:
            occupied.add(netaddr.IPNetwork(child.prefix))
        free = self.bounds - occupied
        intervals = list(free.iter_ipranges())[: self.limit]
        child_candidate = None
        requested = None
        if requested_prefix_length not in (None, ""):
            try:
                requested = int(str(requested_prefix_length).lstrip("/"))
            except ValueError:
                requested = -1
            maximum = 32 if self.network.version == 4 else 128
            if self.network.prefixlen < requested <= maximum:
                for cidr in free.iter_cidrs():
                    if cidr.prefixlen <= requested:
                        child_candidate = str(cidr if cidr.prefixlen == requested else next(cidr.subnet(requested)))
                        break
        return {
            "known": True,
            "reason": "",
            "next_ip": str(next(free.__iter__())) if free.size else None,
            "available_count": free.size,
            "free_ranges": [{"start": str(item[0]), "end": str(item[-1]), "size": item.size} for item in intervals],
            "child_candidate": child_candidate,
            "requested_prefix_length": requested,
        }

    def conflicts(self, candidate):
        candidate = str(candidate or "").strip()
        if not candidate:
            return None
        ips, ranges, children, complete = self._visible()
        if not complete:
            return {"candidate": candidate, "known": False, "conflicts": ["hidden_occupancy"]}
        try:
            maximum = 32 if self.network.version == 4 else 128
            target = netaddr.IPNetwork(candidate) if "/" in candidate else netaddr.IPNetwork(f"{candidate}/{maximum}")
        except (netaddr.AddrFormatError, ValueError):
            return {"candidate": candidate, "known": True, "conflicts": ["invalid_address_or_cidr"]}
        conflicts = []
        if target.version != self.network.version or not target in self.network:
            conflicts.append("outside_prefix")
        ip_hits = [str(value) for value in ips.annotate(host=HOST_ADDRESS).filter(
            address__host_between=(target[0], target[-1])
        ).values_list("address", flat=True)]
        if ip_hits:
            conflicts.append(f"existing_ip_objects:{len(ip_hits)}")
        if any(int(item.start_address.ip) <= int(target[-1]) and int(item.end_address.ip) >= int(target[0]) for item in ranges):
            conflicts.append("ip_range_overlap")
        if any(int(netaddr.IPNetwork(item.prefix)[0]) <= int(target[-1]) and
               int(netaddr.IPNetwork(item.prefix)[-1]) >= int(target[0]) for item in children):
            conflicts.append("child_prefix_overlap")
        return {"candidate": candidate, "vrf_id": self.prefix.vrf_id, "known": True,
                "conflicts": conflicts, "available": not conflicts}
