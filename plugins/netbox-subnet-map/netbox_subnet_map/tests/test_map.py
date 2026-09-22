import json
from netaddr import IPNetwork
from unittest.mock import patch

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from core.models import ObjectType
from dcim.models import Device, DeviceRole, DeviceType, Interface, MACAddress, Manufacturer, Site
from ipam.models import FHRPGroup, IPAddress, IPRange, Prefix, VRF
from tenancy.models import Tenant
from users.models import ObjectPermission, User
from virtualization.models import VirtualMachine, VMInterface

from netbox_subnet_map.services.assembler import SubnetMapAssembler


class MapTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # Fail closed if anyone accidentally invokes this suite against inventory.
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Subnet Map fixtures require an isolated test database")
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="map-admin", password="test-only-password")
        cls.tenant = Tenant.objects.create(name="Example tenant", slug="example-tenant")
        cls.vrf = VRF.objects.create(name="Example VRF", enforce_unique=False)
        cls.prefix = Prefix.objects.create(prefix="192.0.2.0/24", vrf=cls.vrf, tenant=cls.tenant)

    def assemble(self, prefix=None, user=None, options=None, **kwargs):
        return SubnetMapAssembler(prefix or self.prefix, user or self.user, options).assemble(**kwargs)

    def ip(self, address="192.0.2.10/24", **kwargs):
        return IPAddress.objects.create(address=address, vrf=self.vrf, **kwargs)

    def record(self, result, host="192.0.2.10"):
        return next(row for row in result["records"] if row["address_host"] == host)

    def test_normal_grid_zero_mutation_and_no_validation(self):
        self.ip()
        before = (Prefix.objects.count(), IPAddress.objects.count(), MACAddress.objects.count())
        with patch.object(IPAddress, "full_clean", side_effect=AssertionError("GET validation")), patch.object(Prefix, "full_clean", side_effect=AssertionError("GET validation")):
            result = self.assemble()
        self.assertEqual(result["metrics"]["usable"], 254)
        self.assertEqual(result["metrics"]["operationally_unclaimed"], 253)
        self.assertEqual(len(result["records"]), 254)
        self.assertEqual(before, (Prefix.objects.count(), IPAddress.objects.count(), MACAddress.objects.count()))
        record = self.record(result)
        self.assertEqual(record["ip_objects"][0]["assignment"]["type"], "Not assigned")

    def test_contextual_actions_preserve_readonly_allocation_entry(self):
        available = self.record(self.assemble())
        action = available["contextual_actions"][0]
        self.assertEqual(action["kind"], "allocate")
        self.assertEqual(action["reason"], "Requires permission to add IP addresses")
        self.assertFalse(action["enabled"])
        self.assertNotIn("url", action)

        enabled = self.record(SubnetMapAssembler(
            self.prefix, self.user, can_allocate=True
        ).assemble())["contextual_actions"][0]
        self.assertTrue(enabled["enabled"])
        self.assertIn("/subnet-map/allocate/?", enabled["url"])
        self.ip("192.0.2.10/32")
        self.ip("192.0.2.10/24")
        existing = self.record(self.assemble())
        self.assertNotIn("allocate", [a["kind"] for a in existing["contextual_actions"]])
        opens = [a for a in existing["contextual_actions"] if a["kind"] == "open_ip"]
        self.assertEqual({a["object_id"] for a in opens}, {ip["id"] for ip in existing["ip_objects"]})
        for action in existing["contextual_actions"]:
            if action["kind"] == "edit":
                self.assertFalse(action["enabled"])
                self.assertNotIn("url", action)
                self.assertEqual(action["reason"], "Requires permission to change IP addresses")

    def test_edit_action_uses_native_netbox_form_and_permission_gate(self):
        obj = self.ip("192.0.2.10/32")
        readonly = self.record(self.assemble())
        edit = next(action for action in readonly["contextual_actions"] if action["kind"] == "edit")
        self.assertFalse(edit["enabled"])
        self.assertNotIn("url", edit)
        writable = self.record(SubnetMapAssembler(
            self.prefix, self.user, can_change=True
        ).assemble())
        edit = next(action for action in writable["contextual_actions"] if action["kind"] == "edit")
        self.assertTrue(edit["enabled"])
        self.assertEqual(edit["url"], reverse("ipam:ipaddress_edit", kwargs={"pk": obj.pk}))

    def test_range_and_populated_range(self):
        for populated in (False, True):
            with self.subTest(populated=populated):
                interval = IPRange.objects.create(start_address=IPNetwork("192.0.2.8/24"), end_address=IPNetwork("192.0.2.12/24"), vrf=self.vrf, mark_populated=populated)
                result = self.assemble()
                record = self.record(result)
                self.assertIn("In IPRange", record["derived_states"])
                self.assertNotIn("Available", record["derived_states"])
                self.assertEqual(record["allocation_state"], "blocked")
                self.assertEqual(result["metrics"]["in_ranges"], 5)
                action = record["contextual_actions"][0]
                self.assertFalse(action["enabled"])
                self.assertNotIn("url", action)
                self.assertIn("populated IPRange" if populated else "requires review", action["reason"])
                interval.delete()

    def test_boundary_spanning_range(self):
        IPRange.objects.create(start_address=IPNetwork("192.0.1.254/22"), end_address=IPNetwork("192.0.2.12/22"), vrf=self.vrf, mark_populated=True)
        result = self.assemble()
        self.assertEqual(self.record(result)["allocation_blockers"], ["populated_range"])
        self.assertEqual(result["metrics"]["in_ranges"], 12)

    def test_children_and_nested_children(self):
        Prefix.objects.create(prefix="192.0.2.0/26", vrf=self.vrf)
        Prefix.objects.create(prefix="192.0.2.0/27", vrf=self.vrf)
        result = self.assemble()
        record = self.record(result)
        self.assertEqual(len(record["child_prefix_ids"]), 2)
        self.assertIn("In Child Prefix", record["derived_states"])
        self.assertEqual(result["metrics"]["in_children"], 63)
        self.assertEqual(result["metrics"]["operationally_unclaimed"], 191)
        self.assertEqual([a["kind"] for a in record["contextual_actions"]], ["open_child", "open_child"])
        for action in record["contextual_actions"]:
            self.assertTrue(action["enabled"])
            self.assertTrue(result["children_by_id"][action["child_prefix_id"]]["map_url"].endswith("/subnet-map/"))

    def test_container_no_grid_and_no_cross_vrf_helper(self):
        prefix = Prefix.objects.create(prefix="198.51.100.0/24", status="container")
        other = Prefix.objects.create(prefix="198.51.100.0/26", vrf=self.vrf)
        result = self.assemble(prefix)
        self.assertFalse(result["grid"])
        self.assertEqual(result["children_by_id"], {})
        self.assertIsNone(result["metrics"]["operationally_unclaimed"])

    def test_plural_objects_and_stored_masks(self):
        self.ip("192.0.2.10/32")
        self.ip("192.0.2.10/24", role="anycast")
        result = self.assemble()
        record = self.record(result)
        self.assertEqual(len(record["ip_objects"]), 2)
        self.assertEqual({ip["address"] for ip in record["ip_objects"]}, {"192.0.2.10/32", "192.0.2.10/24"})
        self.assertEqual(record["marker"], "2")
        self.assertEqual(result["metrics"]["operationally_unclaimed"], 253)

    def test_small_prefixes_pool_and_utilized(self):
        for cidr, pool, utilized, count in [("198.51.100.0/31", False, False, 2), ("198.51.100.8/32", False, False, 1), ("198.51.100.16/30", True, False, 4), ("198.51.100.32/30", False, True, 2)]:
            with self.subTest(cidr=cidr):
                p = Prefix.objects.create(prefix=cidr, vrf=self.vrf, is_pool=pool, mark_utilized=utilized)
                result = self.assemble(p)
                self.assertEqual(result["metrics"]["usable"], count)
                self.assertEqual(result["metrics"]["operationally_unclaimed"], p.get_available_ips().size)

    def test_ipv6_and_large_threshold(self):
        for cidr in ("2001:db8::/64", "2001:db8:1::/127", "198.18.0.0/16"):
            result = self.assemble(Prefix.objects.create(prefix=cidr, vrf=self.vrf))
            self.assertFalse(result["grid"])
            self.assertEqual(result["records"], [])
        self.assertFalse(self.assemble(options={"host_grid_limit": 100})["grid"])

    def make_interface(self):
        role = DeviceRole.objects.create(name="Database", slug="database")
        manufacturer = Manufacturer.objects.create(name="Example", slug="example")
        kind = DeviceType.objects.create(model="Example model", slug="example-model", manufacturer=manufacturer)
        site = Site.objects.create(name="Example site", slug="example-site")
        device = Device.objects.create(name="Example device", role=role, device_type=kind, site=site)
        return Interface.objects.create(name="eth0", device=device, type="virtual")

    def test_physical_interface_primary_and_other_macs(self):
        interface = self.make_interface()
        primary = MACAddress.objects.create(mac_address="02:00:00:00:00:01", assigned_object=interface)
        MACAddress.objects.create(mac_address="02:00:00:00:00:02", assigned_object=interface)
        interface.primary_mac_address = primary
        interface.save()
        self.ip(assigned_object=interface)
        assignment = self.record(self.assemble())["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["type"], "dcim.Interface")
        self.assertEqual(assignment["function"], "Database")
        self.assertEqual(assignment["primary_mac"], "02:00:00:00:00:01")
        self.assertEqual(assignment["other_macs"], ["02:00:00:00:00:02"])

    def test_vm_interface_and_no_mac(self):
        vm = VirtualMachine.objects.create(name="Example VM")
        interface = VMInterface.objects.create(name="ens1", virtual_machine=vm)
        self.ip(assigned_object=interface)
        assignment = self.record(self.assemble())["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["type"], "virtualization.VMInterface")
        self.assertEqual(assignment["parent"], "Example VM")
        self.assertEqual(assignment["primary_mac"], "Not recorded")

    def test_fhrp_only_gateway_derivation(self):
        group = FHRPGroup.objects.create(protocol="vrrp2", group_id=20)
        self.ip(assigned_object=group)
        self.ip("192.0.2.1/24")
        result = self.assemble()
        self.assertIn("Gateway", self.record(result)["derived_states"])
        self.assertNotIn("Gateway", self.record(result, "192.0.2.1")["derived_states"])

    def test_null_tenant_independent_and_status(self):
        self.ip(status="reserved")
        result = self.assemble()
        record = self.record(result)
        self.assertEqual(record["ip_objects"][0]["tenant"], "—")
        self.assertEqual(result["prefix"]["tenant"], "Example tenant")
        self.assertEqual(record["netbox_statuses"], ["Reserved"])
        self.assertNotIn("Reserved", record["derived_states"])

    def test_vrf_overlap(self):
        other_vrf = VRF.objects.create(name="Other", enforce_unique=False)
        Prefix.objects.create(prefix=self.prefix.prefix, vrf=other_vrf)
        IPAddress.objects.create(address="192.0.2.10/24", vrf=other_vrf, description="must not leak")
        IPRange.objects.create(start_address=IPNetwork("192.0.2.8/24"), end_address=IPNetwork("192.0.2.12/24"), vrf=other_vrf)
        Prefix.objects.create(prefix="192.0.2.0/26", vrf=other_vrf)
        result = self.assemble()
        self.assertEqual(result["metrics"]["operationally_unclaimed"], 254)
        self.assertEqual(self.record(result)["ip_objects"], [])
        self.assertNotIn("must not leak", json.dumps(result))

    def permission(self, user, model, constraints=None):
        permission = ObjectPermission.objects.create(name=f"View {model.__name__}", actions=["view"], constraints=constraints)
        permission.users.add(user)
        permission.object_types.add(ObjectType.objects.get_for_model(model))

    def test_hidden_occupancy_not_false_available(self):
        self.ip(description="hidden secret")
        user = User.objects.create_user(username="limited")
        self.permission(user, Prefix)
        self.permission(user, IPAddress, {"pk": 999999})
        self.permission(user, IPRange)
        result = self.assemble(user=user)
        self.assertFalse(result["visibility_complete"])
        self.assertIsNone(result["metrics"]["operationally_unclaimed"])
        self.assertEqual(self.record(result)["derived_states"], ["Not evaluated"])
        action = self.record(result)["contextual_actions"][0]
        self.assertFalse(action["enabled"])
        self.assertIn("not confirmed", action["reason"])
        self.assertNotIn("hidden secret", json.dumps(result))

    def test_hidden_assignment_labels(self):
        interface = self.make_interface()
        self.ip(assigned_object=interface)
        user = User.objects.create_user(username="ip-reader")
        for model in (Prefix, IPAddress, IPRange):
            self.permission(user, model)
        result = self.assemble(user=user)
        assignment = self.record(result)["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["label"], "Not visible")
        self.assertNotIn("Example device", json.dumps(result))

    def test_route_permissions_tab_readonly_and_escaping(self):
        self.ip(description='</script><img src=x onerror=alert(1)>')
        url = reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk})
        client = Client()
        self.assertEqual(client.get(url).status_code, 302)
        reader = User.objects.create_user(username="no-permission")
        client.force_login(reader)
        self.assertEqual(client.get(url).status_code, 403)
        client.force_login(self.user)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subnet Map")
        self.assertContains(response, 'id="sm-data"')
        self.assertNotContains(response, '<img src=x onerror=alert(1)>')
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(client, method)(url).status_code, 405)
        native = client.get(reverse("ipam:prefix", kwargs={"pk": self.prefix.pk}))
        self.assertContains(native, url)

    def test_object_permission_denies_other_prefix(self):
        reader = User.objects.create_user(username="prefix-limited")
        self.permission(reader, Prefix, {"pk": 999999})
        client = Client()
        client.force_login(reader)
        self.assertEqual(client.get(reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk})).status_code, 404)

    def test_query_count_does_not_grow_per_ip(self):
        interface = self.make_interface()
        self.ip(assigned_object=interface)
        self.assemble()  # Warm content-type caches.
        with CaptureQueriesContext(connection) as small:
            self.assemble()
        for index in range(11, 31):
            self.ip(f"192.0.2.{index}/24", assigned_object=interface)
        with CaptureQueriesContext(connection) as larger:
            self.assemble()
        self.assertLessEqual(len(larger), len(small) + 1)
        self.assertLess(len(larger), 35)

    def test_host_pagination_keeps_duplicate_objects_together(self):
        self.ip("192.0.2.10/32")
        self.ip("192.0.2.10/24")
        self.ip("192.0.2.11/24")
        result = self.assemble(options={"host_grid_limit": 1, "hosts_per_page": 1})
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(len(result["records"][0]["ip_objects"]), 2)
        self.assertEqual(result["pagination"]["pages"], 2)

    def reader(self, *, children=True, ranges=True, ips=True):
        user = User.objects.create_user(username="restricted-reader")
        self.permission(user, Prefix, None if children else {"pk": self.prefix.pk})
        self.permission(user, VRF)
        self.permission(user, Tenant)
        if ranges:
            self.permission(user, IPRange)
        if ips:
            self.permission(user, IPAddress)
        return user

    def assert_no_candidates(self, result, blocker):
        for record in result["records"]:
            self.assertNotEqual(record["allocation_state"], "candidate")
            self.assertIn(blocker, record["allocation_blockers"])
            self.assertFalse(any(a["enabled"] for a in record["contextual_actions"] if a["kind"] == "allocate"))

    def test_structured_allocation_and_numeric_identities(self):
        result = self.assemble()
        record = self.record(result)
        self.assertEqual(record["allocation_state"], "candidate")
        self.assertEqual(record["allocation_blockers"], [])
        self.assertNotIn("allocatable", record)
        self.assertEqual((record["prefix_id"], record["vrf_id"]), (self.prefix.pk, self.vrf.pk))
        self.assertEqual(result["prefix"]["prefix_id"], self.prefix.pk)
        self.assertEqual(result["prefix"]["vrf_id"], self.vrf.pk)
        self.ip()
        record = self.record(self.assemble())
        self.assertEqual(record["allocation_state"], "blocked")
        self.assertEqual(record["allocation_blockers"], ["existing_ip"])
        # Actions must not depend on translatable presentation strings or colors.
        from netbox_subnet_map.services.assembler import AddressRecord
        candidate = AddressRecord("192.0.2.77", "77", allocation_state="candidate",
                                  derived_states=["translated"], visual_state="reserved")
        self.assertEqual(
            SubnetMapAssembler._contextual_actions(candidate)[0]["reason"],
            "Requires permission to add IP addresses",
        )
        global_prefix = Prefix.objects.create(prefix="198.51.100.0/30")
        global_result = self.assemble(global_prefix)
        self.assertIsNone(global_result["prefix"]["vrf_id"])
        self.assertTrue(global_result["prefix"]["vrf_identity_visible"])
        self.assertEqual(global_result["prefix"]["vrf"], "Global")

    def test_candidate_impossible_with_incomplete_visibility(self):
        self.ip()
        result = self.assemble(user=self.reader(ips=False))
        self.assertFalse(result["visibility_complete"])
        self.assert_no_candidates(result, "visibility_incomplete")

    def test_occupancy_truncated_is_unknown(self):
        for cidr in ("192.0.2.0/27", "192.0.2.32/27"):
            Prefix.objects.create(prefix=cidr, vrf=self.vrf)
        self.ip("192.0.2.200/24")
        result = self.assemble(options={"related_object_limit": 1})
        self.assertTrue(result["visibility_complete"])
        self.assertTrue(result["occupancy_truncated"])
        self.assertFalse(result["grid"])
        self.assert_no_candidates(result, "occupancy_truncated")
        self.assertIsNone(result["metrics"]["netbox_available"])

    def test_numeric_pagination_order_and_sql(self):
        for host in (100, 2, 10):
            self.ip(f"192.0.2.{host}/24")
        self.ip("192.0.2.10/32")
        pages = []
        with CaptureQueriesContext(connection) as queries:
            for number in (1, 2, 3):
                result = self.assemble(options={"host_grid_limit": 1, "hosts_per_page": 1}, page=number)
                pages.append(result["records"][0]["address_host"])
                if number == 2:
                    self.assertEqual(len(result["records"][0]["ip_objects"]), 2)
        self.assertEqual(pages, ["192.0.2.2", "192.0.2.10", "192.0.2.100"])
        grouping = [q["sql"] for q in queries if "GROUP BY" in q["sql"] and "ORDER BY" in q["sql"]]
        self.assertTrue(grouping)
        self.assertTrue(any("::inet" in sql or " AS inet" in sql for sql in grouping))
        self.assertTrue(any('HOST("ipam_ipaddress"."address")' in sql and "BETWEEN" in sql for sql in grouping))
        self.assertTrue(all("<<=" not in q["sql"] for q in queries))
        print("M15_NUMERIC_PAGINATION_SQL", grouping[0])

    def assert_grid_blocks(self, cidr, count):
        prefix = Prefix.objects.create(prefix=cidr, vrf=self.vrf)
        result = self.assemble(prefix)
        records = [r for r in result["records"] if r["in_grid"]]
        self.assertTrue(result["grid"])
        self.assertEqual(len({r["short_label"] for r in records}), len(records))
        self.assertEqual(len({r["grid_block"] for r in records}), count)
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("ipam:prefix_subnet_map", kwargs={"pk": prefix.pk}))
        self.assertContains(response, 'class="sm-block-heading"', count=count)

    def test_unique_slash23_labels(self):
        self.assert_grid_blocks("198.18.8.0/23", 2)

    def test_unique_slash22_labels(self):
        self.assert_grid_blocks("198.18.8.0/22", 4)

    def test_hard_grid_ceiling(self):
        prefix = Prefix.objects.create(prefix="198.18.0.0/16", vrf=self.vrf)
        with patch.object(Prefix, "get_available_ips", side_effect=AssertionError("Unbounded membership")):
            result = self.assemble(prefix, options={"host_grid_limit": 65536})
        self.assertFalse(result["grid"])
        self.assertEqual(result["records"], [])
        self.assertEqual(SubnetMapAssembler(prefix, self.user, {"host_grid_limit": 65536}).grid_limit, 1024)
        self.assert_grid_blocks("198.18.8.0/22", 4)

    def test_non_grid_count_path_and_metric_semantics(self):
        self.ip("192.0.2.10/32")
        self.ip("192.0.2.10/24")
        self.ip("192.0.2.200/24")
        IPRange.objects.create(start_address=IPNetwork("192.0.2.8/24"),
                               end_address=IPNetwork("192.0.2.12/24"), vrf=self.vrf)
        Prefix.objects.create(prefix="192.0.2.0/26", vrf=self.vrf)
        grid = self.assemble()
        with patch.object(Prefix, "get_available_ips", side_effect=AssertionError("Non-grid membership")), \
             patch.object(self.prefix, "get_available_ip_count", wraps=self.prefix.get_available_ip_count) as count:
            result = self.assemble(options={"host_grid_limit": 1})
            count.assert_called_once_with()
        self.assertEqual(result["metrics"]["netbox_available"], 252)
        self.assertEqual(result["metrics"]["operationally_unclaimed"], 190)
        self.assertEqual(result["metrics"], grid["metrics"])
        self.assertNotEqual(result["metrics"]["netbox_available"], result["metrics"]["operationally_unclaimed"])

    def test_slash22_normalized_payload_budget(self):
        prefix = Prefix.objects.create(prefix="198.18.8.0/22", vrf=self.vrf)
        for index in range(16):
            start = IPNetwork(f"198.18.8.{index * 8}/22")
            end = IPNetwork(f"198.18.11.{255 - index * 8}/22")
            IPRange.objects.create(start_address=start, end_address=end, vrf=self.vrf,
                                   description=f"Range {index}: " + "x" * 140, mark_populated=index % 2 == 0)
        Prefix.objects.create(prefix="198.18.9.0/24", vrf=self.vrf)
        result = self.assemble(prefix)
        payload = json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode()
        expanded_records = [
            dict(record, containing_ranges=[result["ranges_by_id"][pk] for pk in record["range_ids"]],
                 containing_child_prefixes=[result["children_by_id"][pk] for pk in record["child_prefix_ids"]])
            for record in result["records"]
        ]
        expanded_size = len(json.dumps(dict(result, records=expanded_records), separators=(",", ":"), ensure_ascii=False).encode())
        self.assertEqual(len(result["ranges_by_id"]), 16)
        self.assertEqual(len(result["records"]), 1022)
        self.assertTrue(all("containing_ranges" not in r and "containing_child_prefixes" not in r for r in result["records"]))
        self.assertLess(len(payload), 1024 * 1024)
        self.assertLess(len(payload), expanded_size * 0.35)
        print("M15_PAYLOAD", json.dumps({"hosts": 1022, "overlapping_ranges": 16, "bytes": len(payload),
                                       "expanded_comparison_bytes": expanded_size, "budget_bytes": 1048576}))

    def test_hidden_range_no_candidate_or_metadata(self):
        hidden = IPRange.objects.create(start_address=IPNetwork("192.0.2.8/24"), end_address=IPNetwork("192.0.2.12/24"),
                                        vrf=self.vrf, description="hidden-range-label", mark_populated=True)
        result = self.assemble(user=self.reader(ranges=False))
        self.assert_no_candidates(result, "visibility_incomplete")
        self.assertEqual(result["ranges_by_id"], {})
        self.assertTrue(all(r["range_ids"] == [] for r in result["records"]))
        self.assertNotIn("hidden-range-label", json.dumps(result))
        self.assertNotIn(hidden.get_absolute_url(), json.dumps(result))

    def test_hidden_child_no_candidate_or_metadata(self):
        hidden = Prefix.objects.create(prefix="192.0.2.0/26", vrf=self.vrf)
        result = self.assemble(user=self.reader(children=False))
        self.assert_no_candidates(result, "visibility_incomplete")
        self.assertEqual(result["children_by_id"], {})
        self.assertTrue(all(r["child_prefix_ids"] == [] for r in result["records"]))
        self.assertNotIn(hidden.get_absolute_url(), json.dumps(result))

    def test_hidden_mac_no_value_or_endpoint(self):
        interface = self.make_interface()
        hidden = MACAddress.objects.create(mac_address="02:00:00:00:00:FE", assigned_object=interface)
        interface.primary_mac_address = hidden
        interface.save()
        self.ip(assigned_object=interface)
        user = self.reader()
        for model in (Interface, Device, DeviceRole):
            self.permission(user, model)
        result = self.assemble(user=user)
        assignment = self.record(result)["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["primary_mac"], "Not visible")
        self.assertEqual(assignment["other_macs"], [])
        self.assertNotIn(str(hidden.mac_address), json.dumps(result))
        self.assertNotIn(hidden.get_absolute_url(), json.dumps(result))

    def test_visible_interface_hidden_device(self):
        interface = self.make_interface()
        self.ip(assigned_object=interface)
        user = self.reader()
        self.permission(user, Interface)
        result = self.assemble(user=user)
        assignment = self.record(result)["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["interface"], "eth0")
        self.assertEqual(assignment["parent"], "Not visible")
        self.assertIsNone(assignment["parent_url"])
        self.assertNotIn("Example device", json.dumps(result))
        self.assertNotIn(interface.device.get_absolute_url(), json.dumps(result))

    def test_visible_vm_interface_hidden_vm(self):
        vm = VirtualMachine.objects.create(name="Hidden VM parent")
        interface = VMInterface.objects.create(name="ens1", virtual_machine=vm)
        self.ip(assigned_object=interface)
        user = self.reader()
        self.permission(user, VMInterface)
        result = self.assemble(user=user)
        assignment = self.record(result)["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["interface"], "ens1")
        self.assertEqual(assignment["parent"], "Not visible")
        self.assertIsNone(assignment["parent_url"])
        self.assertNotIn(vm.name, json.dumps(result))
        self.assertNotIn(vm.get_absolute_url(), json.dumps(result))

    def test_visible_parent_hidden_role(self):
        interface = self.make_interface()
        self.ip(assigned_object=interface)
        user = self.reader()
        for model in (Interface, Device):
            self.permission(user, model)
        result = self.assemble(user=user)
        assignment = self.record(result)["ip_objects"][0]["assignment"]
        self.assertEqual(assignment["parent"], "Example device")
        self.assertEqual(assignment["function"], "Not visible")
        self.assertNotIn("Database", json.dumps(result))
        self.assertNotIn(interface.device.role.get_absolute_url(), json.dumps(result))

    def test_mixed_visible_hidden_objects(self):
        visible = self.ip("192.0.2.10/32")
        hidden = self.ip("192.0.2.10/24", description="hidden-ip-label")
        user = self.reader(ips=False)
        self.permission(user, IPAddress, {"pk": visible.pk})
        result = self.assemble(user=user)
        self.assert_no_candidates(result, "visibility_incomplete")
        record = self.record(result)
        self.assertEqual([ip["id"] for ip in record["ip_objects"]], [visible.pk])
        self.assertNotIn("hidden-ip-label", json.dumps(result))
        self.assertNotIn(hidden.get_absolute_url(), json.dumps(result))
        self.assertIn("existing_ip", record["allocation_blockers"])

    def test_hidden_vrf_identity_not_disclosed(self):
        user = User.objects.create_user(username="no-vrf")
        for model in (Prefix, IPAddress, IPRange, Tenant):
            self.permission(user, model)
        result = self.assemble(user=user)
        self.assertIsNone(result["prefix"]["vrf_id"])
        self.assertFalse(result["prefix"]["vrf_identity_visible"])
        self.assertNotIn(self.vrf.name, json.dumps(result))
        self.assert_no_candidates(result, "vrf_not_visible")
