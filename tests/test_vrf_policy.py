"""M1.6 policy tests. Run only with NetBox's isolated Django test database."""
import importlib.util
import os
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from ipam.models import IPAddress, Prefix, VRF
from netaddr import IPNetwork
from tenancy.models import Tenant

_candidate_path = os.environ.get("M16_VALIDATOR_PATH")
if _candidate_path:
    _spec = importlib.util.spec_from_file_location("m16_candidate", _candidate_path)
    policy = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(policy)
else:
    from validators import netbox_demo_validators as policy


class VRFPolicyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if not connection.settings_dict["NAME"].startswith("test_"):
            raise RuntimeError("Validator fixtures require an isolated test database")
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.prod = Tenant.objects.create(name="PROD", slug="prod")
        cls.dev = Tenant.objects.create(name="DEV", slug="dev")
        cls.dr = Tenant.objects.create(name="DR", slug="dr")
        cls.app = Tenant.objects.create(name="APP-TEAM", slug="app-team")
        cls.a = VRF.objects.create(name="VRF-A", enforce_unique=False)
        cls.b = VRF.objects.create(name="VRF-B", enforce_unique=False)

    def prefix(self, tenant=None, vrf=None, cidr="10.10.10.0/24", saved=True):
        obj = Prefix(prefix=IPNetwork(cidr), tenant=tenant, vrf=vrf)
        if saved:
            obj.save()  # Normal fixture construction in TestCase; not a production validation bypass.
        return obj

    def ip(self, tenant=None, vrf=None, address="10.10.10.77/24"):
        return IPAddress(address=IPNetwork(address), tenant=tenant, vrf=vrf)

    def validate_prefix(self, obj):
        policy.EnvironmentPrefixValidator().validate(obj, None)

    def validate_ip(self, obj):
        policy.EnvironmentIPAddressValidator().validate(obj, None)

    def test_P1_same_tenant_same_vrf_overlap_preserved(self):
        self.prefix(self.prod, self.a)
        self.validate_prefix(self.prefix(self.prod, self.a, saved=False))

    def test_P2_cross_tenant_same_vrf_fails(self):
        # Legacy/inconsistent fixtures isolate overlap behavior from the mapping rule.
        self.prefix(self.dev, self.a)
        with self.assertRaisesRegex(ValidationError, "IP OVERLAP CONFLICT"):
            self.validate_prefix(self.prefix(self.prod, self.a, saved=False))

    def test_P3_cross_tenant_other_vrf_independent(self):
        self.prefix(self.dev, self.b)
        self.validate_prefix(self.prefix(self.prod, self.a, saved=False))

    def test_P4_same_cidr_global_and_vrf_independent(self):
        self.prefix(self.prod)
        self.validate_prefix(self.prefix(self.prod, self.a, saved=False))

    def test_P5_global_ignores_vrf_overlap(self):
        self.prefix(self.dev, self.a)
        self.validate_prefix(self.prefix(self.prod, saved=False))

    def test_P6_vrf_ignores_global_overlap(self):
        self.prefix(self.dev)
        self.validate_prefix(self.prefix(self.prod, self.a, saved=False))

    def test_P7_supernet_enforcement_unchanged(self):
        for tenant, cidr in ((self.prod, "10.10.0.0/16"), (self.dev, "10.20.0.0/16"), (self.dr, "10.30.0.0/16")):
            with self.subTest(tenant=tenant.slug):
                self.validate_prefix(self.prefix(tenant, self.a, cidr, saved=False))
                with self.assertRaisesRegex(ValidationError, "outside"):
                    self.validate_prefix(self.prefix(tenant, self.a, "192.0.2.0/24", saved=False))

    def test_P8_missing_prefix_tenant_fails(self):
        with self.assertRaisesRegex(ValidationError, "every Prefix requires"):
            self.validate_prefix(self.prefix(vrf=self.a, saved=False))

    def test_I1_global_uses_only_global_parent(self):
        self.prefix(self.prod)
        self.prefix(self.dev, self.a, "10.10.10.0/25")
        self.validate_ip(self.ip(self.prod))

    def test_I2_vrf_uses_only_its_parent(self):
        self.prefix(self.prod, self.a)
        self.validate_ip(self.ip(self.prod, self.a))

    def test_I3_same_cidr_global_vrf_selects_vrf(self):
        self.prefix(self.dev)
        self.prefix(self.prod, self.a)
        self.validate_ip(self.ip(self.prod, self.a))

    def test_I4_same_cidr_other_vrf_never_selected(self):
        self.prefix(self.dev, self.b)
        self.prefix(self.prod, self.a)
        self.validate_ip(self.ip(self.prod, self.a))

    def test_I5_matching_tenant_passes(self):
        self.prefix(self.prod, self.a)
        self.validate_ip(self.ip(self.prod, self.a))

    def test_I6_mismatched_tenant_fails(self):
        self.prefix(self.prod, self.a)
        with self.assertRaisesRegex(ValidationError, "does not match parent Prefix owner"):
            self.validate_ip(self.ip(self.dev, self.a))

    def test_I7_null_ip_tenant_fails(self):
        self.prefix(self.prod, self.a)
        with self.assertRaisesRegex(ValidationError, "every IP address requires"):
            self.validate_ip(self.ip(vrf=self.a))

    def test_I8_no_same_vrf_parent_fails_without_fallback(self):
        self.prefix(self.prod)
        with self.assertRaisesRegex(ValidationError, "no valid containing Prefix in its VRF"):
            self.validate_ip(self.ip(self.prod, self.a))
        self.prefix(self.prod, self.a)
        with self.assertRaisesRegex(ValidationError, "no valid containing Prefix in its VRF"):
            self.validate_ip(self.ip(self.prod, self.b))

    def test_I9_other_vrf_more_specific_parent_ignored(self):
        self.prefix(self.prod, self.a, "10.10.0.0/16")
        self.prefix(self.dev, self.b, "10.10.10.0/25")
        self.validate_ip(self.ip(self.prod, self.a))

    def test_I10_global_most_specific_policy_preserved(self):
        self.prefix(self.dev, cidr="10.10.0.0/16")
        self.prefix(self.prod)
        self.validate_ip(self.ip(self.prod))
        with self.assertRaisesRegex(ValidationError, "does not match"):
            self.validate_ip(self.ip(self.dev))

    def test_existing_prefix_excludes_itself(self):
        obj = self.prefix(self.prod, self.a)
        # In-memory tenant change: the stored row must not conflict with itself.
        obj.tenant = self.dev
        with self.assertRaises(ValidationError) as error:
            self.validate_prefix(obj)
        self.assertIn("outside", str(error.exception))
        self.assertNotIn("IP OVERLAP CONFLICT", str(error.exception))

    def test_global_same_vrf_cross_tenant_still_fails(self):
        self.prefix(self.dev)
        with self.assertRaisesRegex(ValidationError, "IP OVERLAP CONFLICT"):
            self.validate_prefix(self.prefix(self.prod, saved=False))

    def test_equal_specificity_same_owner_is_deterministic(self):
        first = self.prefix(self.prod, self.a)
        self.prefix(self.prod, self.a)
        with CaptureQueriesContext(connection) as queries:
            self.validate_ip(self.ip(self.prod, self.a))
        self.assertTrue(any("MASKLEN" in q["sql"] and "ORDER BY" in q["sql"] and "LIMIT 1" in q["sql"] for q in queries))
        print("M16_PARENT_SQL", queries[0]["sql"])
        self.assertLess(first.pk, Prefix.objects.filter(vrf=self.a).order_by("-pk").first().pk)

    def test_equal_specificity_conflicting_owners_fail_clearly(self):
        self.prefix(self.prod, self.a)
        self.prefix(self.dev, self.a)
        for tenant in (self.prod, self.dev):
            with self.subTest(tenant=tenant.slug), self.assertRaisesRegex(ValidationError, "ambiguous parent Prefix ownership"):
                self.validate_ip(self.ip(tenant, self.a))

    def test_native_duplicate_prefix_permission_setting(self):
        self.prefix(self.prod, self.a)
        duplicate = self.prefix(self.prod, self.a, saved=False)
        duplicate.full_clean()  # Native NetBox permits same-owner duplicates when enforce_unique=False.
        self.a.enforce_unique = True
        self.a.save()
        with self.assertRaisesRegex(ValidationError, "Duplicate prefix"):
            duplicate.full_clean()

    def test_unknown_tenant_and_app_team_not_relaxed(self):
        with self.assertRaisesRegex(ValidationError, "no approved supernet"):
            self.validate_prefix(self.prefix(self.app, self.a, saved=False))
        self.prefix(self.prod, self.a)
        with self.assertRaisesRegex(ValidationError, "does not match"):
            self.validate_ip(self.ip(self.app, self.a))

    def test_ipv6_does_not_cross_address_families(self):
        self.prefix(self.prod, self.a, "2001:db8::/64")
        with self.assertRaisesRegex(ValidationError, "no valid containing Prefix"):
            self.validate_ip(self.ip(self.prod, self.a))
        # The approved supernets remain IPv4-only; reject IPv6 rather than raising TypeError.
        with self.assertRaisesRegex(ValidationError, "outside"):
            self.validate_prefix(self.prefix(self.prod, self.a, "2001:db8:1::/64", saved=False))
        self.validate_ip(self.ip(self.prod, self.a, "2001:db8::77/128"))

    def test_global_never_uses_only_vrf_parent(self):
        self.prefix(self.prod, self.a)
        with self.assertRaisesRegex(ValidationError, "no valid containing Prefix"):
            self.validate_ip(self.ip(self.prod))

    def test_validation_does_not_save(self):
        parent = self.prefix(self.prod, self.a)
        with patch.object(Prefix, "save", side_effect=AssertionError("Unexpected save")), patch.object(IPAddress, "save", side_effect=AssertionError("Unexpected save")):
            self.validate_prefix(parent)
            self.validate_ip(self.ip(self.prod, self.a))
