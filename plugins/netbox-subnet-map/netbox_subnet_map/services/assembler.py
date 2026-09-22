"""One request-scoped read model. No validation, saves, or inventory persistence.

All related-object labels come from permission-restricted batches. Native helpers
are used for availability only when IP/range/child visibility is complete within
the selected Prefix. Otherwise candidate availability is withheld for the whole
view, without revealing which host has hidden occupancy.
"""
from collections import defaultdict
from dataclasses import dataclass, field

import netaddr
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import Cast
from django.urls import reverse
from urllib.parse import urlencode
from dcim.models import Device, DeviceRole, Interface, MACAddress
from ipam.models import FHRPGroup, IPAddress, IPRange, Prefix, Role, VLAN, VRF
from ipam.fields import IPAddressField
from ipam.lookups import Host
from tenancy.models import Tenant
from virtualization.models import VirtualMachine, VMInterface

MAX_GRID_HOSTS = 1024
HOST_ADDRESS = Cast(Host("address"), output_field=IPAddressField())


@dataclass
class AddressRecord:
    address_host: str
    short_label: str
    ip_objects: list = field(default_factory=list)
    prefix_id: int = 0
    vrf_id: int | None = None
    vrf_identity_visible: bool = True
    range_ids: list = field(default_factory=list)
    child_prefix_ids: list = field(default_factory=list)
    netbox_statuses: list = field(default_factory=list)
    derived_states: list = field(default_factory=list)
    allocation_state: str = "unknown"
    allocation_blockers: list = field(default_factory=list)
    allocation_message: str = ""
    grid_block: str = ""
    visual_state: str = "unknown"
    marker: str = "?"
    in_grid: bool = False
    special: bool = False
    accessible_label: str = ""
    contextual_actions: list = field(default_factory=list)


def _bounded(value, default, maximum):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _size(intervals, bounds):
    return (netaddr.IPSet(intervals) & bounds).size


class SubnetMapAssembler:
    @staticmethod
    def _allocation(record, *, visibility_complete, truncated, container, usable, native_free, populated):
        blockers = []
        if record.ip_objects:
            blockers.append("existing_ip")
        if populated:
            blockers.append("populated_range")
        if record.child_prefix_ids:
            blockers.append("child_prefix")
        if record.range_ids and not populated:
            blockers.append("range_context")
        if container:
            blockers.append("container_prefix")
        if not usable:
            blockers.append("outside_usable_space")
        unknown = []
        if not visibility_complete:
            unknown.append("visibility_incomplete")
        if truncated:
            unknown.append("occupancy_truncated")
        if not record.vrf_identity_visible:
            unknown.append("vrf_not_visible")
        if native_free is False and not blockers:
            blockers.append("native_unavailable")
        if native_free is None and not blockers and not unknown:
            unknown.append("availability_not_evaluated")
        record.allocation_blockers = blockers + unknown
        record.allocation_state = "unknown" if unknown else ("blocked" if blockers else "candidate")
        record.allocation_message = {
            "candidate": "Candidate only; write permissions and validation must be rechecked in M3.",
            "blocked": "Allocation is blocked by the selected address context.",
            "unknown": "Allocation eligibility is not confirmed.",
        }[record.allocation_state]

    @staticmethod
    def _contextual_actions(record, can_allocate=False, editable_ids=frozenset()):
        """Read-only action descriptors, never write authorization.

        M3 must re-evaluate permissions, occupancy and native validation at save.
        No client-side color or flag can authorize a write.
        """
        actions = []
        for ip in record.ip_objects:
            can_change = ip["id"] in editable_ids
            edit = {"kind": "edit", "label": "Edit", "object_id": ip["id"],
                    "object_address": ip["address"], "enabled": can_change}
            if can_change:
                edit["url"] = reverse("ipam:ipaddress_edit", kwargs={"pk": ip["id"]})
            else:
                edit["reason"] = "Requires permission to change IP addresses"
            actions.extend([
                edit,
                {"kind": "open_ip", "label": "Open IP Object", "object_id": ip["id"],
                 "object_address": ip["address"], "enabled": True, "url": ip["url"]},
            ])
        for child_id in record.child_prefix_ids:
            actions.append({"kind": "open_child", "label": "Open Child Subnet Map",
                            "child_prefix_id": child_id, "enabled": True})
        if {"existing_ip", "child_prefix", "container_prefix"} & set(record.allocation_blockers):
            return actions
        if record.allocation_state == "unknown":
            reason = "Allocation disabled — availability is not confirmed"
        elif "populated_range" in record.allocation_blockers:
            reason = "Allocation disabled — populated IPRange"
        elif record.allocation_state == "candidate" and can_allocate:
            actions.append({
                "kind": "allocate", "label": "Allocate IP", "enabled": True,
                "url": reverse("ipam:prefix_subnet_map_allocate", kwargs={"pk": record.prefix_id}) + "?" + urlencode({
                    "host": record.address_host, "_quickadd": "True", "target": "subnet-map",
                }),
            })
            return actions
        elif record.allocation_state == "candidate":
            reason = "Requires permission to add IP addresses"
        elif "range_context" in record.allocation_blockers:
            reason = "Allocation disabled — IPRange context requires review"
        else:
            reason = "Allocation disabled — availability is not confirmed"
        actions.append({"kind": "allocate", "label": "Allocate IP", "enabled": False, "reason": reason})
        return actions

    def __init__(self, prefix, user, options=None, *, can_allocate=False, can_change=False):
        self.prefix = prefix
        self.user = user
        options = options or {}
        self.grid_limit = _bounded(options.get("host_grid_limit"), 1024, MAX_GRID_HOSTS)
        self.page_size = _bounded(options.get("hosts_per_page"), 128, 1000)
        self.related_limit = _bounded(options.get("related_object_limit"), 2000, 10000)
        self.can_allocate = can_allocate
        self.can_change = can_change

    def _visible(self, model, ids):
        ids = {pk for pk in ids if pk is not None}
        return {obj.pk: obj for obj in model.objects.filter(pk__in=ids).restrict(self.user, "view")} if ids else {}

    @staticmethod
    def _label(mapping, pk):
        return str(mapping[pk]) if pk in mapping else ("Not visible" if pk is not None else "—")

    def _assignments(self, ips):
        """Fixed batches per supported type; never follow an unrestricted GFK."""
        cts = ContentType.objects.get_for_models(Interface, VMInterface, FHRPGroup)
        type_models = {ct.pk: model for model, ct in cts.items()}
        objects = {}
        for ct_id, model in type_models.items():
            objects[ct_id] = self._visible(model, [ip.assigned_object_id for ip in ips if ip.assigned_object_type_id == ct_id])
        interfaces = list(objects[cts[Interface].pk].values())
        vm_interfaces = list(objects[cts[VMInterface].pk].values())
        devices = self._visible(Device, [obj.device_id for obj in interfaces])
        vms = self._visible(VirtualMachine, [obj.virtual_machine_id for obj in vm_interfaces])
        roles = self._visible(DeviceRole, [obj.role_id for obj in [*devices.values(), *vms.values()]])
        primary_ids = [obj.primary_mac_address_id for obj in [*interfaces, *vm_interfaces] if obj.primary_mac_address_id]
        mac_query = Q(pk__in=primary_ids)
        for model, items in ((Interface, interfaces), (VMInterface, vm_interfaces)):
            mac_query |= Q(assigned_object_type_id=cts[model].pk, assigned_object_id__in=[obj.pk for obj in items])
        macs = list(MACAddress.objects.filter(mac_query).restrict(self.user, "view")) if interfaces or vm_interfaces else []
        mac_by_id = {obj.pk: obj for obj in macs}
        mac_by_interface = defaultdict(list)
        for mac in macs:
            mac_by_interface[(mac.assigned_object_type_id, mac.assigned_object_id)].append(mac)
        result = {}
        for ip in ips:
            data = {"type": "Not assigned", "label": "Not assigned", "url": None,
                    "parent": "—", "parent_url": None, "interface": "—", "function": "—",
                    "site": "—", "primary_mac": "Not recorded", "other_macs": [], "gateway": False}
            if ip.assigned_object_id is None:
                result[ip.pk] = data
                continue
            model = type_models.get(ip.assigned_object_type_id)
            obj = objects.get(ip.assigned_object_type_id, {}).get(ip.assigned_object_id)
            if obj is None:
                data.update(type="Not visible", label="Not visible")
            else:
                data.update(type=model._meta.label, label=str(obj), url=obj.get_absolute_url())
                if model is FHRPGroup:
                    data.update(parent=str(obj), parent_url=obj.get_absolute_url(), gateway=True)
                else:
                    parent = devices.get(obj.device_id) if model is Interface else vms.get(obj.virtual_machine_id)
                    data.update(interface=str(obj), parent=str(parent) if parent else "Not visible",
                                parent_url=parent.get_absolute_url() if parent else None,
                                function=self._label(roles, parent.role_id) if parent else "—")
                    if parent:
                        site = getattr(parent, "site", None)
                        if site is None and getattr(parent, "cluster", None):
                            site = getattr(parent.cluster, "site", None)
                        data["site"] = str(site) if site else "—"
                    primary = mac_by_id.get(obj.primary_mac_address_id)
                    data["primary_mac"] = str(primary.mac_address) if primary else ("Not visible" if obj.primary_mac_address_id else "Not recorded")
                    data["other_macs"] = [str(mac.mac_address) for mac in mac_by_interface[(ip.assigned_object_type_id, obj.pk)] if mac.pk != obj.primary_mac_address_id]
            result[ip.pk] = data
        return result

    def assemble(self, page=1):
        p = self.prefix
        network = netaddr.IPNetwork(p.prefix)
        first, last = p.usable_ip_bounds
        usable_bounds = netaddr.IPSet([netaddr.IPRange(first, last)])
        # Explicit VRF identity even for global containers (native helpers can
        # intentionally include other VRFs in that case).
        all_ips = IPAddress.objects.filter(vrf_id=p.vrf_id, address__host_between=(
            netaddr.IPAddress(network.first, version=network.version),
            netaddr.IPAddress(network.last, version=network.version)))
        all_ranges = IPRange.objects.filter(vrf_id=p.vrf_id,
            start_address__host__inet__lte=netaddr.IPAddress(network.last, version=network.version),
            end_address__host__inet__gte=netaddr.IPAddress(network.first, version=network.version))
        all_children = Prefix.objects.filter(vrf_id=p.vrf_id, prefix__net_contained=str(p.prefix)).exclude(pk=p.pk)
        visible_ips = all_ips.restrict(self.user, "view")
        visible_ranges = all_ranges.restrict(self.user, "view")
        visible_children = all_children.restrict(self.user, "view")
        editable_ids = set(
            IPAddress.objects.filter(pk__in=visible_ips.values("pk")).restrict(self.user, "change").values_list("pk", flat=True)
        ) if self.can_change else set()
        visibility_complete = all(not qs.exclude(pk__in=allowed.values("pk")).exists() for qs, allowed in (
            (all_ips, visible_ips), (all_ranges, visible_ranges), (all_children, visible_children)))
        ip_count = visible_ips.count()
        ranges = list(visible_ranges.order_by("start_address", "pk")[:self.related_limit + 1])
        children = list(visible_children.order_by("prefix", "pk")[:self.related_limit + 1])
        truncated = len(ranges) > self.related_limit or len(children) > self.related_limit
        ranges, children = ranges[:self.related_limit], children[:self.related_limit]
        complete = visibility_complete and not truncated
        grid = network.version == 4 and p.status != "container" and p.usable_size <= self.grid_limit and not truncated
        # Page by distinct host, so objects sharing a host are never split.
        host_page = None
        if grid:
            ips = list(visible_ips.order_by(HOST_ADDRESS, "pk"))
        else:
            hosts = visible_ips.order_by().annotate(host_address=HOST_ADDRESS).values("host_address").annotate(
                objects=Count("pk")).order_by("host_address")
            host_page = Paginator(hosts, self.page_size).get_page(page)
            ips = list(visible_ips.filter(address__host__inet__in=[
                str(row["host_address"].ip) for row in host_page]).order_by(HOST_ADDRESS, "pk"))
        tenants = self._visible(Tenant, [p.tenant_id] + [obj.tenant_id for obj in [*ips, *ranges, *children]])
        roles = self._visible(Role, [obj.role_id for obj in ranges])
        vrfs = self._visible(VRF, [p.vrf_id])
        vrf_identity_visible = p.vrf_id is None or p.vrf_id in vrfs
        visible_vrf_id = p.vrf_id if vrf_identity_visible else None
        vlans = self._visible(VLAN, [p.vlan_id])
        scope = None
        if p.scope_type_id and p.scope_id:
            scope_model = ContentType.objects.get_for_id(p.scope_type_id).model_class()
            if scope_model and hasattr(scope_model.objects.all(), "restrict"):
                scope = self._visible(scope_model, [p.scope_id]).get(p.scope_id)
        range_data = {obj.pk: {"id": obj.pk, "label": str(obj), "url": obj.get_absolute_url(),
                       "description": obj.description, "start": str(obj.start_address), "end": str(obj.end_address),
                       "status": obj.get_status_display(), "role": self._label(roles, obj.role_id),
                       "tenant": self._label(tenants, obj.tenant_id), "mark_populated": obj.mark_populated,
                       "mark_utilized": obj.mark_utilized} for obj in ranges}
        vrf_label = self._label(vrfs, p.vrf_id) if p.vrf_id else "Global"
        child_data = {obj.pk: {"id": obj.pk, "label": str(obj.prefix), "url": obj.get_absolute_url(),
                       "map_url": reverse("ipam:prefix_subnet_map", kwargs={"pk": obj.pk}),
                       "status": obj.get_status_display(), "tenant": self._label(tenants, obj.tenant_id),
                       "vrf": vrf_label} for obj in children}
        range_intervals = [netaddr.IPRange(obj.start_address.ip, obj.end_address.ip) for obj in ranges]
        child_intervals = [netaddr.IPNetwork(obj.prefix) for obj in children]
        availability_known = complete and vrf_identity_visible and not (p.vrf_id is None and p.status == "container")
        # Only bounded grids materialize native membership. Non-grid views use
        # the NetBox 4.6.9 count helper and distinct-host aggregate instead.
        native_available = p.get_available_ips() if availability_known and grid else None
        netbox_available = (native_available.size if grid else p.get_available_ip_count()) if availability_known else None
        # Native prefix helper includes only fully contained ranges. Include
        # boundary-spanning populated ranges in this explicitly derived view.
        populated = netaddr.IPSet([interval for obj, interval in zip(ranges, range_intervals) if obj.mark_populated])
        special_space = netaddr.IPSet([*range_intervals, *child_intervals])
        operationally_unclaimed = None
        if availability_known and p.status != "container":
            if grid:
                operationally_unclaimed = (native_available - special_space).size
            else:
                occupied_outside_special = visible_ips.filter(address__host_between=(first, last)).count_distinct_hosts(
                    exclude_intervals=[(interval[0], interval[-1]) for interval in (special_space & usable_bounds).iter_ipranges()])
                operationally_unclaimed = max((usable_bounds - special_space).size - occupied_outside_special, 0)
        assignments = self._assignments(ips)
        by_host = defaultdict(list)
        for ip in ips:
            a = assignments[ip.pk]
            by_host[str(ip.address.ip)].append({"id": ip.pk, "address": str(ip.address),
                "status": ip.get_status_display(), "status_value": ip.status,
                "role": ip.get_role_display() if ip.role else "—", "tenant": self._label(tenants, ip.tenant_id),
                "dns_name": ip.dns_name, "description": ip.description, "url": ip.get_absolute_url(),
                "created": ip.created.isoformat() if ip.created else None,
                "last_updated": ip.last_updated.isoformat() if ip.last_updated else None,
                "assignment": a})
        hosts = set(by_host)
        if grid:
            hosts.update(str(netaddr.IPAddress(host)) for host in range(int(first), int(last) + 1))
        records = []
        for host in sorted(hosts, key=lambda value: int(netaddr.IPAddress(value))):
            address = netaddr.IPAddress(host)
            short_label = ".".join(host.split(".")[-2:]) if network.version == 4 and network.prefixlen < 24 else (
                host.split(".")[-1] if network.version == 4 else host)
            record = AddressRecord(host, short_label, prefix_id=p.pk, vrf_id=visible_vrf_id,
                                   vrf_identity_visible=vrf_identity_visible,
                                   ip_objects=by_host[host], in_grid=grid and first <= address <= last,
                                   grid_block=str(netaddr.IPNetwork(host + "/24").cidr) if grid and network.prefixlen < 24 else "")
            record.range_ids = [obj.pk for obj, interval in zip(ranges, range_intervals) if address in interval]
            record.child_prefix_ids = [obj.pk for obj, interval in zip(children, child_intervals) if address in interval]
            record.netbox_statuses = list(dict.fromkeys(ip["status"] for ip in record.ip_objects))
            states = record.derived_states
            if record.ip_objects:
                states.append("Existing IP")
                record.visual_state, record.marker = "existing", "●"
                if any(ip["status_value"] == "reserved" for ip in record.ip_objects):
                    record.visual_state, record.marker = "reserved", "S"
            if record.range_ids:
                states.append("In IPRange")
                record.visual_state, record.marker = "range", "R"
            if record.child_prefix_ids:
                states.append("In Child Prefix")
                record.visual_state, record.marker = "child", "C"
            if any(ip["assignment"]["gateway"] for ip in record.ip_objects):
                states.append("Gateway")
                record.visual_state, record.marker = "gateway", "G"
            if len(record.ip_objects) > 1:
                states.append(f"Multiple Objects ({len(record.ip_objects)})")
                record.visual_state, record.marker = "multiple", str(len(record.ip_objects))
            record.special = bool(states)
            self._allocation(record, visibility_complete=visibility_complete, truncated=truncated,
                             container=p.status == "container", usable=first <= address <= last,
                             native_free=address in native_available if native_available is not None else None,
                             populated=address in populated)
            if not states:
                if record.allocation_state == "candidate":
                    states.append("Available")
                    record.visual_state, record.marker = "available", "·"
                else:
                    states.append("Not evaluated" if not availability_known else "Outside native available space")
            record.accessible_label = "; ".join([host, *record.netbox_statuses, *states, f"{len(record.ip_objects)} visible IP objects"])
            record.contextual_actions = self._contextual_actions(record, self.can_allocate, editable_ids)
            records.append(vars(record))  # Shallow: shared normalized metadata is never copied per host.
        notices = []
        if not complete:
            notices.append("Availability is not evaluated because this view has incomplete visibility or a summary limit. Empty cells are not confirmed free.")
        if truncated:
            notices.append(f"Related summaries are limited to {self.related_limit} objects. Use the native Prefix lists to inspect further records.")
        if p.mark_utilized:
            notices.append("This Prefix is marked utilized in NetBox. Utilization and host availability are separate native concepts.")
        if not grid:
            notices.append("Host grid is disabled for containers, IPv6, or address spaces above the configured limit. Browse child prefixes, ranges and paginated allocated hosts below.")
        if p.vrf_id is None and p.status == "container":
            notices.append("Host availability is not evaluated for a global container because NetBox's container helper spans VRFs. This map retains the selected VRF boundary.")
        if not vrf_identity_visible:
            notices.append("VRF identity is not visible; availability and allocation eligibility are not evaluated.")
        return {"prefix": {"prefix_id": p.pk, "vrf_id": visible_vrf_id, "vrf_identity_visible": vrf_identity_visible,
                 "cidr": str(p.prefix), "status": p.get_status_display(),
                 "tenant": self._label(tenants, p.tenant_id), "vrf": vrf_label,
                 "vlan": self._label(vlans, p.vlan_id), "scope": str(scope) if scope else ("Not visible" if p.scope_id else "—")},
                "metrics": {"usable": p.usable_size, "ip_objects": ip_count,
                            "in_ranges": _size(range_intervals, usable_bounds) if not truncated else None,
                            "in_children": _size(child_intervals, usable_bounds) if not truncated else None,
                            "netbox_available": netbox_available, "operationally_unclaimed": operationally_unclaimed},
                "grid": grid, "records": records, "ranges_by_id": range_data, "children_by_id": child_data,
                "notices": notices, "visibility_complete": visibility_complete, "occupancy_truncated": truncated,
                "pagination": {"number": host_page.number, "pages": host_page.paginator.num_pages,
                               "previous": host_page.previous_page_number() if host_page.has_previous() else None,
                               "next": host_page.next_page_number() if host_page.has_next() else None} if host_page else None}
