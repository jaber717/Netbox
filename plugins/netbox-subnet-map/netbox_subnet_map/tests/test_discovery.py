import json

from django.db import connection
from django.test import TestCase
from netaddr import IPNetwork

from dcim.models import Device, DeviceRole, DeviceType, Interface, Manufacturer, Site
from ipam.models import IPAddress, IPRange, Prefix, VRF, VLAN
from tenancy.models import Tenant
from users.models import User
from virtualization.models import VirtualMachine, VMInterface

from netbox_subnet_map.services.assembler import SubnetMapAssembler
from netbox_subnet_map.services.discovery import FreeSpaceFinder, filter_subnet_map


class DiscoveryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Subnet Map discovery tests require an isolated test database")
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="discovery-admin", password="test-password")
        cls.tenant = Tenant.objects.create(name="Discovery tenant", slug="discovery-tenant")
        cls.vrf = VRF.objects.create(name="Discovery VRF", enforce_unique=False)
        cls.vlan = VLAN.objects.create(name="Discovery VLAN", vid=120)
        cls.prefix = Prefix.objects.create(prefix="192.0.2.0/24", vrf=cls.vrf, tenant=cls.tenant, vlan=cls.vlan)
        cls.site = Site.objects.create(name="Discovery Site", slug="discovery-site")
        role = DeviceRole.objects.create(name="Router", slug="router")
        manufacturer = Manufacturer.objects.create(name="Discovery vendor", slug="discovery-vendor")
        device_type = DeviceType.objects.create(model="Discovery model", slug="discovery-model", manufacturer=manufacturer)
        device = Device.objects.create(name="edge-router", role=role, device_type=device_type, site=cls.site)
        interface = Interface.objects.create(name="xe-0/0/0", device=device, type="1000base-t")
        cls.ip = IPAddress.objects.create(address="192.0.2.10/24", vrf=cls.vrf, tenant=cls.tenant,
                                          status="active", dns_name="router.example.test", assigned_object=interface)
        vm = VirtualMachine.objects.create(name="app-vm")
        vm_interface = VMInterface.objects.create(name="ens3", virtual_machine=vm)
        IPAddress.objects.create(address="192.0.2.20/24", vrf=cls.vrf, dns_name="vm.example.test", assigned_object=vm_interface)
        IPRange.objects.create(start_address=IPNetwork("192.0.2.30/24"), end_address=IPNetwork("192.0.2.39/24"),
                               vrf=cls.vrf, mark_populated=True)
        Prefix.objects.create(prefix="192.0.2.64/27", vrf=cls.vrf)

    def result(self, **params):
        data = SubnetMapAssembler(self.prefix, self.user, can_change=True).assemble()
        return filter_subnet_map(data, params)

    def test_search_and_all_named_filters(self):
        cases = {
            "q": "edge-router", "address": "192.0.2.10", "prefix": "192.0.2.0/24",
            "vrf": "Discovery VRF", "tenant": "Discovery tenant", "status": "Active",
            "device": "edge-router", "interface": "xe-0/0/0", "dns_name": "router.example.test",
            "vlan": "Discovery VLAN", "site": "Discovery Site",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                result = self.result(**{key: value})
                self.assertTrue(any(row["address_host"] == "192.0.2.10" for row in result["records"]))

    def test_cidr_filter_and_vm_filter(self):
        cidr = self.result(address="192.0.2.16/28")
        self.assertTrue(all(IPNetwork(f'{row["address_host"]}/32') in IPNetwork("192.0.2.16/28") for row in cidr["records"]))
        vm = self.result(vm="app-vm")
        self.assertEqual([row["address_host"] for row in vm["records"]], ["192.0.2.20"])

    def test_free_space_excludes_ip_range_and_child_prefix(self):
        result = FreeSpaceFinder(self.prefix, self.user).summary("/27")
        self.assertTrue(result["known"])
        self.assertEqual(result["next_ip"], "192.0.2.1")
        self.assertNotEqual(result["child_candidate"], "192.0.2.0/27")
        payload = json.dumps(result)
        self.assertNotIn('"start": "192.0.2.30"', payload)

    def test_conflict_simulator_and_vrf_isolation(self):
        finder = FreeSpaceFinder(self.prefix, self.user)
        self.assertIn("existing_ip_objects:1", finder.conflicts("192.0.2.10")["conflicts"])
        self.assertIn("ip_range_overlap", finder.conflicts("192.0.2.32/28")["conflicts"])
        self.assertIn("child_prefix_overlap", finder.conflicts("192.0.2.64/28")["conflicts"])
        self.assertTrue(finder.conflicts("192.0.2.50")["available"])
        other = VRF.objects.create(name="Other VRF", enforce_unique=False)
        IPAddress.objects.create(address="192.0.2.50/24", vrf=other)
        self.assertTrue(finder.conflicts("192.0.2.50")["available"])

    def test_31_and_32_free_space(self):
        for cidr, expected in (("198.51.100.0/31", "198.51.100.0"), ("198.51.100.8/32", "198.51.100.8")):
            with self.subTest(cidr=cidr):
                prefix = Prefix.objects.create(prefix=cidr, vrf=self.vrf)
                self.assertEqual(FreeSpaceFinder(prefix, self.user).summary()["next_ip"], expected)

    def test_mark_utilized_fails_closed(self):
        prefix = Prefix.objects.create(prefix="198.51.100.16/30", vrf=self.vrf, mark_utilized=True)
        self.assertFalse(FreeSpaceFinder(prefix, self.user).summary()["known"])
