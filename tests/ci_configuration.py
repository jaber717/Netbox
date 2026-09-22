"""CI-only NetBox configuration; every value is non-production."""
import os

ALLOWED_HOSTS = ["*"]
DATABASE = {
    "NAME": os.environ.get("POSTGRES_DB", "netbox"),
    "USER": os.environ.get("POSTGRES_USER", "netbox"),
    "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "ci-only-password"),
    "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
    "PORT": 5432,
}
REDIS = {
    "tasks": {"HOST": "127.0.0.1", "PORT": 6379, "PASSWORD": "", "DATABASE": 0, "SSL": False},
    "caching": {"HOST": "127.0.0.1", "PORT": 6379, "PASSWORD": "", "DATABASE": 1, "SSL": False},
}
SECRET_KEY = "ci-only-not-a-production-secret-key-000000000000000000000000"
API_TOKEN_PEPPERS = {1: "ci-only-not-a-production-pepper-000000000000000000000000"}
PLUGINS = ["netbox_subnet_map"]
PLUGINS_CONFIG = {"netbox_subnet_map": {"host_grid_limit": 1024, "free_range_limit": 32}}
