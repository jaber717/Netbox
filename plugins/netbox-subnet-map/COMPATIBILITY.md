# Compatibility

## Tested

NetBox **4.6.9** only. Compatibility must be revalidated before widening the supported range.

The plugin uses supported `PluginConfig` and `register_model_view` behavior for Prefix integration. Its 4.6.9 implementation also depends on Host/INET transforms, `Prefix.usable_ip_bounds`, `get_available_ip_count()` availability semantics, native `IPAddressForm` Quick Add behavior, and `mark_utilized` semantics. These dependencies require regression testing for every additional NetBox version.
