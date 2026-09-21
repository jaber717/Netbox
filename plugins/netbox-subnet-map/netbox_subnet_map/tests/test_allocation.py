import threading
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from core.choices import ObjectChangeActionChoices
from core.models import ObjectChange, ObjectType
from ipam.forms import IPAddressForm
from ipam.models import IPAddress, IPRange, Prefix, VRF
from netaddr import IPNetwork
from tenancy.models import Tenant
from users.models import ObjectPermission, User

from netbox_subnet_map.services.assembler import SubnetMapAssembler


def grant(user, model, actions, constraints=None, name=None):
    permission = ObjectPermission.objects.create(
        name=name or f"{'-'.join(actions)} {model._meta.label} {user.username}",
        actions=actions,
        constraints=constraints,
    )
    permission.users.add(user)
    permission.object_types.add(ObjectType.objects.get_for_model(model))
    return permission


class AllocationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Subnet Map allocation tests require an isolated test database")
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="allocation-admin", password="test-password")
        cls.tenant = Tenant.objects.create(name="Allocation tenant", slug="allocation-tenant")
        cls.other_tenant = Tenant.objects.create(name="Wrong tenant", slug="wrong-tenant")
        cls.prefix = Prefix.objects.create(prefix="192.0.2.0/24", tenant=cls.tenant)

    def url(self, prefix=None):
        return reverse("ipam:prefix_subnet_map_allocate", kwargs={"pk": (prefix or self.prefix).pk})

    def data(self, host="192.0.2.77", tenant=None, **extra):
        payload = {
            "host": host,
            "_quickadd": "True",
            "status": "active",
            "role": "",
            "tenant": str((tenant or self.tenant).pk),
            "dns_name": "",
            "description": "allocated from grid",
        }
        payload.update(extra)
        return payload

    def logged_in(self, user=None, *, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(user or self.admin)
        return client

    def test_map_stays_get_only_and_candidate_action_is_permission_gated(self):
        map_url = reverse("ipam:prefix_subnet_map", kwargs={"pk": self.prefix.pk})
        client = self.logged_in()
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(client, method)(map_url).status_code, 405)
        payload = client.get(map_url).context["subnet_map"]
        record = next(item for item in payload["records"] if item["address_host"] == "192.0.2.77")
        action = next(item for item in record["contextual_actions"] if item["kind"] == "allocate")
        self.assertTrue(action["enabled"])
        self.assertIn(self.url(), action["url"])
        self.assertContains(client.get(map_url), 'data-allocation-trigger="192.0.2.77"')
        self.assertContains(client.get(map_url), 'hx-target="#htmx-modal-content"')

    def test_native_quick_add_form_and_server_prefill(self):
        response = self.logged_in().get(self.url(), {"host": "192.0.2.77", "_quickadd": "True"})
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIsInstance(form, IPAddressForm)
        self.assertTrue(form.fields["address"].disabled)
        self.assertTrue(form.fields["vrf"].disabled)
        self.assertEqual(str(form.instance.address), "192.0.2.77/24")
        self.assertEqual(form.instance.tenant_id, self.tenant.pk)
        self.assertContains(response, 'id="id_interface"')
        self.assertContains(response, "hx-post=")

    def test_auth_add_prefix_and_csrf_permissions(self):
        self.assertEqual(Client().post(self.url(), self.data()).status_code, 302)

        no_add = User.objects.create_user(username="no-add")
        grant(no_add, Prefix, ["view"])
        client = self.logged_in(no_add)
        self.assertEqual(client.post(self.url(), self.data()).status_code, 403)

        no_prefix = User.objects.create_user(username="no-prefix")
        grant(no_prefix, IPAddress, ["add"])
        client.force_login(no_prefix)
        self.assertEqual(client.post(self.url(), self.data()).status_code, 404)

        csrf_client = self.logged_in(csrf=True)
        self.assertEqual(csrf_client.post(self.url(), self.data()).status_code, 403)

    def test_valid_global_allocation_and_single_attributed_changelog(self):
        before = ObjectChange.objects.count()
        response = self.logged_in().post(self.url() + "?target=subnet-map", self.data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="quick-add-object"')
        created = IPAddress.objects.get(address="192.0.2.77/24", vrf=None)
        self.assertEqual(created.tenant, self.tenant)
        changes = ObjectChange.objects.filter(
            changed_object_type=ContentType.objects.get_for_model(IPAddress),
            changed_object_id=created.pk,
        )
        self.assertEqual(ObjectChange.objects.count(), before + 1)
        self.assertEqual(changes.count(), 1)
        change = changes.get()
        self.assertEqual(change.action, ObjectChangeActionChoices.ACTION_CREATE)
        self.assertEqual(change.user, self.admin)
        self.assertEqual(change.user_name, self.admin.username)
        self.assertEqual(str(change.request_id), response.headers["X-Request-ID"])

        refreshed = SubnetMapAssembler(self.prefix, self.admin).assemble()
        record = next(item for item in refreshed["records"] if item["address_host"] == "192.0.2.77")
        self.assertEqual(record["allocation_state"], "blocked")
        self.assertEqual(record["ip_objects"][0]["id"], created.pk)
        self.assertEqual(refreshed["metrics"]["netbox_available"], 253)
        self.assertEqual(refreshed["metrics"]["operationally_unclaimed"], 253)

    def test_numbered_vrf_and_same_cidr_other_vrf_do_not_interfere(self):
        vrf = VRF.objects.create(name="Allocation VRF", enforce_unique=False)
        other = VRF.objects.create(name="Other allocation VRF", enforce_unique=False)
        prefix = Prefix.objects.create(prefix="198.51.100.0/24", vrf=vrf, tenant=self.tenant)
        Prefix.objects.create(prefix="198.51.100.0/24", vrf=other, tenant=self.tenant)
        IPAddress.objects.create(address="198.51.100.77/24", vrf=other, tenant=self.tenant)
        response = self.logged_in().post(self.url(prefix), self.data(host="198.51.100.77", vrf=str(other.pk)))
        self.assertEqual(response.status_code, 200)
        created = IPAddress.objects.get(address="198.51.100.77/24", vrf=vrf)
        self.assertEqual(created.vrf_id, vrf.pk)

    def test_tenant_and_native_choice_validation_roll_back(self):
        client = self.logged_in()
        for payload, field in (
            (self.data(tenant=self.other_tenant), "tenant"),
            (self.data(tenant=self.tenant, tenant_override=""), "tenant"),
            (self.data(status="not-a-status"), "status"),
            (self.data(role="not-a-role"), "role"),
        ):
            if "tenant_override" in payload:
                payload["tenant"] = ""
                payload.pop("tenant_override")
            with self.subTest(field=field, payload=payload):
                before = (IPAddress.objects.count(), ObjectChange.objects.count())
                response = client.post(self.url(), payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(before, (IPAddress.objects.count(), ObjectChange.objects.count()))

    def test_existing_populated_range_and_child_are_rejected_by_authoritative_recheck(self):
        client = self.logged_in()
        blockers = []
        IPAddress.objects.create(address="192.0.2.77/24", tenant=self.tenant)
        blockers.append(client.post(self.url(), self.data()).status_code)
        IPAddress.objects.all().delete()
        IPRange.objects.create(
            start_address=IPNetwork("192.0.2.70/24"), end_address=IPNetwork("192.0.2.80/24"),
            tenant=self.tenant, mark_populated=True,
        )
        blockers.append(client.post(self.url(), self.data()).status_code)
        IPRange.objects.all().delete()
        Prefix.objects.create(prefix="192.0.2.64/26", tenant=self.tenant)
        blockers.append(client.post(self.url(), self.data()).status_code)
        self.assertEqual(blockers, [409, 409, 409])
        self.assertFalse(IPAddress.objects.exists())

    def test_outside_network_broadcast_container_and_unknown_rejected(self):
        client = self.logged_in()
        self.assertEqual(client.post(self.url(), self.data(host="198.51.100.77")).status_code, 409)
        self.assertEqual(client.post(self.url(), self.data(host="192.0.2.0")).status_code, 409)
        self.assertEqual(client.post(self.url(), self.data(host="192.0.2.255")).status_code, 409)
        container = Prefix.objects.create(prefix="203.0.113.0/24", status="container", tenant=self.tenant)
        self.assertEqual(client.post(self.url(container), self.data(host="203.0.113.77")).status_code, 409)

        with override_settings(PLUGINS_CONFIG={"netbox_subnet_map": {"related_object_limit": 1}}):
            IPRange.objects.create(start_address=IPNetwork("192.0.2.10/24"), end_address=IPNetwork("192.0.2.11/24"))
            IPRange.objects.create(start_address=IPNetwork("192.0.2.20/24"), end_address=IPNetwork("192.0.2.21/24"))
            self.assertEqual(client.post(self.url(), self.data()).status_code, 409)

    def test_hidden_occupancy_range_and_child_never_candidate(self):
        for kind in ("ip", "range", "child"):
            with self.subTest(kind=kind):
                user = User.objects.create_user(username=f"hidden-{kind}")
                grant(user, IPAddress, ["add"])
                grant(user, Prefix, ["view"], {"pk": self.prefix.pk})
                grant(user, Tenant, ["view"])
                grant(user, IPAddress, ["view"], {"pk": 999999}, name=f"hidden ip view {kind}")
                grant(user, IPRange, ["view"], {"pk": 999999}, name=f"hidden range view {kind}")
                if kind == "ip":
                    obj = IPAddress.objects.create(address="192.0.2.77/24", tenant=self.tenant)
                elif kind == "range":
                    obj = IPRange.objects.create(
                        start_address=IPNetwork("192.0.2.70/24"), end_address=IPNetwork("192.0.2.80/24")
                    )
                else:
                    obj = Prefix.objects.create(prefix="192.0.2.64/26", tenant=self.tenant)
                response = self.logged_in(user).post(self.url(), self.data())
                self.assertEqual(response.status_code, 409)
                obj.delete()

    def test_post_save_object_permission_rejection_rolls_back(self):
        user = User.objects.create_user(username="constrained-add")
        for model in (Prefix, IPAddress, IPRange, Tenant):
            grant(user, model, ["view"])
        grant(user, IPAddress, ["add"], {"tenant_id": self.other_tenant.pk})
        before = (IPAddress.objects.count(), ObjectChange.objects.count())
        response = self.logged_in(user).post(self.url(), self.data())
        self.assertEqual(response.status_code, 200)
        self.assertIn("__all__", response.context["form"].errors)
        self.assertEqual(before, (IPAddress.objects.count(), ObjectChange.objects.count()))

    def test_native_usable_semantics_for_31_32_and_pool(self):
        client = self.logged_in()
        cases = (
            ("198.51.100.0/31", False, "198.51.100.0"),
            ("198.51.100.8/32", False, "198.51.100.8"),
            ("198.51.100.16/30", True, "198.51.100.16"),
            ("198.51.100.16/30", True, "198.51.100.19"),
        )
        for index, (cidr, is_pool, host) in enumerate(cases):
            with self.subTest(cidr=cidr, host=host):
                prefix = Prefix.objects.create(prefix=cidr, is_pool=is_pool, tenant=self.tenant)
                response = client.post(self.url(prefix), self.data(host=host))
                self.assertEqual(response.status_code, 200)
                mask = IPNetwork(cidr).prefixlen
                self.assertTrue(IPAddress.objects.filter(address=f"{host}/{mask}").exists())
                IPAddress.objects.filter(address=f"{host}/{mask}").delete()
                prefix.delete()


class AllocationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Subnet Map concurrency tests require an isolated test database")
        self.admin = User.objects.create_superuser(username="concurrent-admin", password="test-password")
        self.tenant = Tenant.objects.create(name="Concurrent tenant", slug="concurrent-tenant")
        self.vrf = VRF.objects.create(name="Concurrent VRF", enforce_unique=False)
        self.prefix = Prefix.objects.create(prefix="198.18.0.0/24", vrf=self.vrf, tenant=self.tenant)
        self.url = reverse("ipam:prefix_subnet_map_allocate", kwargs={"pk": self.prefix.pk})

    def test_real_concurrent_duplicate_permitted_and_rendered_as_multiple(self):
        barrier = threading.Barrier(2)
        original = IPAddressForm.is_valid
        statuses = []
        errors = []

        def synchronized_is_valid(form):
            barrier.wait(timeout=20)
            return original(form)

        def allocate():
            close_old_connections()
            try:
                client = Client()
                client.force_login(User.objects.get(pk=self.admin.pk))
                response = client.post(self.url, {
                    "host": "198.18.0.77", "_quickadd": "True", "status": "active", "role": "",
                    "tenant": str(self.tenant.pk), "dns_name": "", "description": "concurrent",
                })
                statuses.append(response.status_code)
            except Exception as exc:  # pragma: no cover - retained for useful thread failure reporting
                errors.append(repr(exc))
            finally:
                close_old_connections()

        with patch.object(IPAddressForm, "is_valid", synchronized_is_valid):
            threads = [threading.Thread(target=allocate), threading.Thread(target=allocate)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(statuses), [200, 200])
        self.assertEqual(IPAddress.objects.filter(address="198.18.0.77/24", vrf=self.vrf).count(), 2)
        record = next(
            item for item in SubnetMapAssembler(self.prefix, self.admin).assemble()["records"]
            if item["address_host"] == "198.18.0.77"
        )
        self.assertIn("Multiple Objects (2)", record["derived_states"])
        self.assertEqual(record["marker"], "2")

    def test_native_enforce_unique_rejects_preexisting_duplicate(self):
        self.vrf.enforce_unique = True
        self.vrf.save()
        IPAddress.objects.create(address="198.18.0.77/24", vrf=self.vrf, tenant=self.tenant)
        form = IPAddressForm(data={
            "address": "198.18.0.77/24", "vrf": self.vrf.pk, "status": "active", "role": "",
            "tenant": self.tenant.pk, "dns_name": "", "description": "duplicate",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("address", form.errors)
