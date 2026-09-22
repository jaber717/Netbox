"""Isolated NetBox 4.6.9 integration-test configuration for CI/lab use."""
from netbox.configuration import *  # noqa: F403

DATABASE = dict(DATABASE)  # noqa: F405
DATABASE["TEST"] = {"NAME": "test_netbox_platform"}
PLUGINS = ["netbox_subnet_map"]
PLUGINS_CONFIG = {
    "netbox_subnet_map": {
        "host_grid_limit": 1024,
        "hosts_per_page": 128,
        "related_object_limit": 2000,
        "free_range_limit": 32,
    }
}
