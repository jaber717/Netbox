"""Idempotently converge reusable NetBox foundation from human-readable YAML.

Run through ``manage.py shell``. This script intentionally owns only taxonomy,
schema, and the explicitly preserved organizational hierarchy. It never creates
racks, devices, addresses, prefixes, VLANs, cables, circuits, or terminations.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from circuits.models import CircuitType, Provider
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from dcim.models import (
    ConsolePortTemplate,
    ConsoleServerPortTemplate,
    DeviceRole,
    DeviceType,
    FrontPortTemplate,
    InterfaceTemplate,
    Location,
    Manufacturer,
    Platform,
    PortTemplateMapping,
    RearPortTemplate,
    Region,
    Site,
)
from extras.models import CustomField, CustomFieldChoiceSet
from ipam.models import RIR, Role
from tenancy.models import Tenant, TenantGroup


DATA_ROOT = Path(os.environ.get("NETBOX_BOOTSTRAP_DATA", "/opt/netbox-company/data/foundation"))
stats = {"created": 0, "updated": 0, "unchanged": 0}
changed_objects = []


def document(name):
    with (DATA_ROOT / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def assign(obj, values):
    changed = False
    fields = {field.name: field for field in obj._meta.concrete_fields}
    for key, value in values.items():
        if key not in fields:
            continue
        field = fields[key]
        current = getattr(obj, key)
        if field.is_relation:
            current_cmp = getattr(current, "pk", current)
            desired_cmp = getattr(value, "pk", value)
            normalized = value
        else:
            current_cmp = field.to_python(current)
            desired_cmp = field.to_python(value)
            normalized = desired_cmp
        if current_cmp != desired_cmp:
            setattr(obj, key, normalized)
            changed = True
    return changed


def converge(model, lookup, desired):
    try:
        obj = model.objects.get(**lookup)
        created = False
    except model.DoesNotExist:
        obj = model(**lookup)
        created = True
    changed = assign(obj, desired)
    if created or changed:
        obj.full_clean()
        obj.save()
        stats["created" if created else "updated"] += 1
        if not created:
            changed_objects.append(f"{obj._meta.label_lower}:{lookup}")
    else:
        stats["unchanged"] += 1
    return obj


def expanded(items):
    for item in items or []:
        item = dict(item)
        if "name_format" not in item:
            yield item
            continue
        template = item.pop("name_format")
        start = int(item.pop("start"))
        end = int(item.pop("end"))
        for number in range(start, end + 1):
            yield {"name": template.format(n=number), **item}


@transaction.atomic
def run():
    organization = document("organization.yml")
    hardware = document("hardware.yml")
    type_data = document("device_types.yml")
    schema = document("schema.yml")
    ipam = document("ipam_taxonomy.yml")
    circuits = document("circuit_taxonomy.yml")

    tenant_groups = {}
    for item in organization.get("tenant_groups", []):
        values = {key: value for key, value in item.items() if key not in {"slug", "parent"}}
        if item.get("parent"):
            values["parent"] = tenant_groups[item["parent"]]
        tenant_groups[item["slug"]] = converge(TenantGroup, {"slug": item["slug"]}, values)

    tenants = {}
    for item in organization.get("tenants", []):
        values = {key: value for key, value in item.items() if key not in {"slug", "group"}}
        values["group"] = tenant_groups[item["group"]]
        tenants[item["slug"]] = converge(Tenant, {"slug": item["slug"]}, values)

    regions = {}
    pending = list(organization.get("regions", []))
    while pending:
        progress = False
        for item in pending[:]:
            if item.get("parent") and item["parent"] not in regions:
                continue
            values = {key: value for key, value in item.items() if key not in {"slug", "parent"}}
            if item.get("parent"):
                values["parent"] = regions[item["parent"]]
            regions[item["slug"]] = converge(Region, {"slug": item["slug"]}, values)
            pending.remove(item)
            progress = True
        if not progress:
            raise RuntimeError("region hierarchy contains an unresolved parent or cycle")

    sites = {}
    for item in organization.get("sites", []):
        values = {
            key: value
            for key, value in item.items()
            if key not in {"slug", "region", "tenant", "company_review_required"}
        }
        values["region"] = regions[item["region"]]
        values["tenant"] = tenants[item["tenant"]]
        sites[item["slug"]] = converge(Site, {"slug": item["slug"]}, values)

    for item in organization.get("locations", []):
        values = {
            key: value
            for key, value in item.items()
            if key not in {"slug", "site", "tenant", "parent", "company_review_required"}
        }
        values["site"] = sites[item["site"]]
        values["tenant"] = tenants[item["tenant"]]
        if item.get("parent"):
            values["parent"] = Location.objects.get(slug=item["parent"], site=values["site"])
        converge(Location, {"slug": item["slug"], "site": values["site"]}, values)

    manufacturers = {}
    for item in hardware.get("manufacturers", []):
        manufacturers[item["slug"]] = converge(
            Manufacturer,
            {"slug": item["slug"]},
            {key: value for key, value in item.items() if key != "slug"},
        )

    for item in hardware.get("device_roles", []):
        converge(DeviceRole, {"slug": item["slug"]}, {key: value for key, value in item.items() if key != "slug"})

    for item in hardware.get("platforms", []):
        values = {key: value for key, value in item.items() if key not in {"slug", "manufacturer"}}
        values["manufacturer"] = manufacturers[item["manufacturer"]]
        converge(Platform, {"slug": item["slug"]}, values)

    for item in type_data.get("device_types", []):
        manufacturer = manufacturers[item["manufacturer"]]
        values = {
            "model": item["model"],
            "slug": item["slug"],
            "u_height": item["u_height"],
            "is_full_depth": item["is_full_depth"],
            "description": "Locally defined to preserve exact Phase 1 component requirements",
        }
        device_type = converge(DeviceType, {"manufacturer": manufacturer, "model": item["model"]}, values)

        for component in expanded(item.get("interfaces")):
            converge(
                InterfaceTemplate,
                {"device_type": device_type, "name": component["name"]},
                {key: value for key, value in component.items() if key != "name"},
            )
        for component in expanded(item.get("console_ports")):
            converge(
                ConsolePortTemplate,
                {"device_type": device_type, "name": component["name"]},
                {key: value for key, value in component.items() if key != "name"},
            )
        for component in expanded(item.get("console_server_ports")):
            converge(
                ConsoleServerPortTemplate,
                {"device_type": device_type, "name": component["name"]},
                {key: value for key, value in component.items() if key != "name"},
            )

        pass_through = item.get("pass_through_ports")
        if pass_through:
            for number in range(1, int(pass_through["count"]) + 1):
                name = str(number)
                rear = converge(
                    RearPortTemplate,
                    {"device_type": device_type, "name": name},
                    {"type": pass_through["type"], "positions": 1},
                )
                front = converge(
                    FrontPortTemplate,
                    {"device_type": device_type, "name": name},
                    {"type": pass_through["type"], "positions": 1},
                )
                converge(
                    PortTemplateMapping,
                    {
                        "device_type": device_type,
                        "front_port": front,
                        "rear_port": rear,
                        "front_port_position": 1,
                        "rear_port_position": 1,
                    },
                    {},
                )

    choice_sets = {}
    for item in schema.get("choice_sets", []):
        values = {key: value for key, value in item.items() if key != "name"}
        choice_sets[item["name"]] = converge(CustomFieldChoiceSet, {"name": item["name"]}, values)

    for item in schema.get("custom_fields", []):
        values = {key: value for key, value in item.items() if key not in {"name", "choice_set", "object_types"}}
        values["choice_set"] = choice_sets[item["choice_set"]]
        field = converge(CustomField, {"name": item["name"]}, values)
        content_types = []
        for label in item.get("object_types", []):
            app_label, model = label.split(".", 1)
            content_types.append(ContentType.objects.get(app_label=app_label, model=model))
        current_ids = set(field.object_types.values_list("pk", flat=True))
        desired_ids = {content_type.pk for content_type in content_types}
        if current_ids != desired_ids:
            field.object_types.set(content_types)
            stats["updated"] += 1

    for item in ipam.get("roles", []):
        converge(Role, {"slug": item["slug"]}, {key: value for key, value in item.items() if key != "slug"})
    for item in ipam.get("rirs", []):
        converge(RIR, {"slug": item["slug"]}, {key: value for key, value in item.items() if key != "slug"})

    for item in circuits.get("circuit_types", []):
        converge(CircuitType, {"slug": item["slug"]}, {key: value for key, value in item.items() if key != "slug"})
    for item in circuits.get("providers", []):
        converge(Provider, {"slug": item["slug"]}, {key: value for key, value in item.items() if key != "slug"})


run()
print(
    "BOOTSTRAP_TAXONOMY "
    f"created={stats['created']} updated={stats['updated']} unchanged={stats['unchanged']}"
)
if changed_objects:
    print("BOOTSTRAP_CHANGED " + "; ".join(changed_objects))
