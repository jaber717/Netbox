from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse

from core.models import ObjectChange
from ipam.models import IPAddress, Prefix, VRF
from tenancy.models import Tenant
from users.models import User


class WorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Subnet Map workflow tests require an isolated test database")
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="workflow-admin", password="test-password")
        cls.tenant = Tenant.objects.create(name="Workflow tenant", slug="workflow-tenant")
        cls.vrf = VRF.objects.create(name="Workflow VRF", enforce_unique=False)
        cls.prefix = Prefix.objects.create(prefix="198.51.100.0/24", vrf=cls.vrf, tenant=cls.tenant)
        cls.ip = IPAddress.objects.create(address="198.51.100.10/24", vrf=cls.vrf, tenant=cls.tenant,
                                          status="active", description="before")

    def logged_in(self):
        client = Client(); client.force_login(self.user); return client

    def test_map_search_and_free_space_controls_render(self):
        response = self.logged_in().get(reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk}), {
            "address": "198.51.100.10", "child_prefix_length": "/27", "simulate": "198.51.100.10",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Search &amp; filter")
        self.assertContains(response, "Free-space finder")
        self.assertContains(response, "existing_ip_objects:1")
        self.assertEqual(response.context["subnet_map"]["filtered_count"], 1)

    def test_native_edit_workflow_updates_and_attributes_changelog(self):
        map_response = self.logged_in().get(reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk}))
        record = next(row for row in map_response.context["subnet_map"]["records"] if row["address_host"] == "198.51.100.10")
        edit = next(action for action in record["contextual_actions"] if action["kind"] == "edit")
        self.assertTrue(edit["enabled"])
        self.assertEqual(edit["url"], reverse("ipam:ipaddress_edit", kwargs={"pk": self.ip.pk}))
        before = ObjectChange.objects.filter(
            changed_object_type=ContentType.objects.get_for_model(IPAddress), changed_object_id=self.ip.pk
        ).count()
        response = self.logged_in().post(edit["url"], {
            "address": str(self.ip.address), "vrf": str(self.vrf.pk), "status": "reserved", "role": "",
            "tenant": str(self.tenant.pk), "dns_name": "edited.example.test", "description": "after",
            "assigned_object_type": "", "assigned_object_id": "", "comments": "",
        })
        self.assertEqual(response.status_code, 302, response.context and response.context.get("form").errors)
        self.ip.refresh_from_db()
        self.assertEqual((self.ip.status, self.ip.dns_name, self.ip.description), ("reserved", "edited.example.test", "after"))
        changes = ObjectChange.objects.filter(
            changed_object_type=ContentType.objects.get_for_model(IPAddress), changed_object_id=self.ip.pk
        )
        self.assertEqual(changes.count(), before + 1)
        self.assertEqual(changes.order_by("-time").first().user, self.user)

    def test_readonly_user_has_no_edit_action(self):
        user = User.objects.create_user(username="workflow-readonly")
        client = Client(); client.force_login(user)
        response = client.get(reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk}))
        self.assertEqual(response.status_code, 403)
