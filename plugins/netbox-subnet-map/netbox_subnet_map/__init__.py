from netbox.plugins import PluginConfig


class SubnetMapConfig(PluginConfig):
    name = "netbox_subnet_map"
    verbose_name = "Subnet Map"
    description = "Permission-aware subnet visualization and native IP allocation on Prefix objects"
    version = "0.3.0"
    base_url = "subnet-map"
    min_version = "4.6.9"
    max_version = "4.6.9"
    default_settings = {
        "host_grid_limit": 1024,
        "hosts_per_page": 128,
        "related_object_limit": 2000,
        "free_range_limit": 32,
    }

    def ready(self):
        super().ready()
        from . import views  # noqa: F401; documented model-view registration


config = SubnetMapConfig
