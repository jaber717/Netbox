import logging
import hashlib

import netaddr
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connections, router, transaction
from django.shortcuts import get_object_or_404, render

from core.signals import clear_events
from ipam.forms import IPAddressForm
from ipam.models import IPAddress, Prefix
from netbox.views import generic
from utilities.exceptions import AbortRequest, PermissionsViolation
from utilities.forms import restrict_form_fields
from utilities.permissions import get_permission_for_model
from utilities.views import ViewTab, register_model_view

from .services.assembler import SubnetMapAssembler
from .services.discovery import FreeSpaceFinder, filter_subnet_map


def _plugin_options():
    return settings.PLUGINS_CONFIG.get("netbox_subnet_map", {})


@register_model_view(Prefix, name="subnet_map", path="subnet-map")
class SubnetMapView(LoginRequiredMixin, generic.ObjectView):
    queryset = Prefix.objects.all()
    template_name = "netbox_subnet_map/map.html"
    tab = ViewTab(label="Subnet Map", permission="ipam.view_prefix", weight=550)
    actions = ()
    http_method_names = ["get", "head", "options"]

    def get_extra_context(self, request, instance):
        subnet_map = SubnetMapAssembler(
            instance,
            request.user,
            _plugin_options(),
            can_allocate=request.user.has_perm("ipam.add_ipaddress"),
            can_change=request.user.has_perm("ipam.change_ipaddress"),
        ).assemble(
            page=request.GET.get("page", 1)
        )
        filter_subnet_map(subnet_map, request.GET)
        finder = FreeSpaceFinder(instance, request.user, limit=_plugin_options().get("free_range_limit", 32))
        return {
            "subnet_map": subnet_map,
            "free_space": finder.summary(request.GET.get("child_prefix_length")),
            "conflict_simulation": finder.conflicts(request.GET.get("simulate")),
        }


@register_model_view(Prefix, name="subnet_map_allocate", path="subnet-map/allocate")
class SubnetMapAllocateView(LoginRequiredMixin, generic.ObjectEditView):
    """Prefix-scoped, candidate-gated adapter around NetBox's native IP create form."""

    queryset = IPAddress.objects.all()
    form = IPAddressForm
    template_name = "netbox_subnet_map/ipaddress_quick_add.html"
    http_method_names = ["get", "post", "head", "options"]

    def get_required_permission(self):
        return get_permission_for_model(IPAddress, "add")

    def get_object(self, **kwargs):
        # The URL's pk identifies the parent Prefix, never an IPAddress to edit.
        return IPAddress()

    def _candidate(self, request, pk, source):
        prefix = get_object_or_404(Prefix.objects.restrict(request.user, "view"), pk=pk)
        raw_host = source.get("host", "")
        try:
            host = str(netaddr.IPAddress(raw_host))
        except (netaddr.AddrFormatError, ValueError):
            return prefix, None, None, "A valid host address is required."

        subnet_map = SubnetMapAssembler(prefix, request.user, _plugin_options()).assemble()
        record = next((item for item in subnet_map["records"] if item["address_host"] == host), None)
        if not subnet_map["grid"] or record is None or not record["in_grid"]:
            return prefix, host, None, "This address is not eligible for grid allocation."
        if record["allocation_state"] != "candidate":
            return prefix, host, record, "This address is no longer an allocation candidate."
        return prefix, host, record, None

    @staticmethod
    def _instance(prefix, host):
        return IPAddress(
            address=f"{host}/{prefix.prefix.prefixlen}",
            vrf_id=prefix.vrf_id,
            tenant_id=prefix.tenant_id,
        )

    @staticmethod
    def _secure_form(form, user):
        # Preserve the native fields/widgets while keeping Prefix identity server-authoritative.
        form.fields["address"].disabled = True
        form.fields["vrf"].disabled = True
        restrict_form_fields(form, user)
        return form

    def _render_form(self, request, prefix, host, form, *, status=200):
        return render(request, self.template_name, {
            "model": IPAddress,
            "form": form,
            "prefix": prefix,
            "host": host,
        }, status=status)

    def _unavailable(self, request, message, *, status=409):
        return render(request, "netbox_subnet_map/allocation_unavailable.html", {
            "message": message,
        }, status=status)

    def get(self, request, *args, **kwargs):
        prefix, host, _record, error = self._candidate(request, kwargs["pk"], request.GET)
        if error:
            return self._unavailable(request, error)
        form = self._secure_form(self.form(instance=self._instance(prefix, host)), request.user)
        return self._render_form(request, prefix, host, form)

    def post(self, request, *args, **kwargs):
        logger = logging.getLogger("netbox_subnet_map.allocation")
        prefix, host, _record, error = self._candidate(request, kwargs["pk"], request.POST)
        if error:
            return self._unavailable(request, error)

        obj = self._instance(prefix, host)
        form = self._secure_form(self.form(data=request.POST, files=request.FILES, instance=obj), request.user)
        if form.is_valid():
            obj._changelog_message = form.cleaned_data.pop("changelog_message", "")
            try:
                alias = router.db_for_write(IPAddress)
                with transaction.atomic(using=alias):
                    # Serialize allocations for this exact VRF/host, then re-read
                    # authoritative occupancy inside the transaction.
                    digest = hashlib.blake2b(
                        f"netbox-subnet-map:{prefix.vrf_id}:{host}".encode(), digest_size=8
                    ).digest()
                    lock_id = int.from_bytes(digest, "big", signed=True)
                    if connections[alias].vendor != "postgresql":
                        raise RuntimeError("Subnet Map allocation requires PostgreSQL transaction locking")
                    with connections[alias].cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
                    prefix, host, _record, error = self._candidate(request, kwargs["pk"], request.POST)
                    if error:
                        return self._unavailable(request, error)
                    obj = form.save()
                    # Same post-save object-permission pattern as NetBox ObjectEditView.
                    if not self.queryset.filter(pk=obj.pk).exists():
                        raise PermissionsViolation()
                logger.info("Created IP address %s (PK: %s) from Subnet Map", obj, obj.pk)
                if "_quickadd" in request.POST:
                    return render(request, "htmx/quick_add_created.html", {
                        "object": obj,
                    })
                return self._unavailable(request, "Quick Add is required for Subnet Map allocation.", status=400)
            except (AbortRequest, PermissionsViolation) as exc:
                form.add_error(None, exc.message)
                clear_events.send(sender=self)

        return self._render_form(request, prefix, host, form)
