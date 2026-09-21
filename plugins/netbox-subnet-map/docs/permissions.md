# Permissions

The map requires login and Prefix view permission. Allocation also requires IPAddress add permission. Object restrictions are honored for Prefixes and related objects. If visibility is incomplete, hidden occupancy is never represented as free and eligibility becomes `unknown`.

The allocation endpoint rechecks state and permissions server-side, uses NetBox CSRF protection, and verifies post-save object visibility. Native request attribution records the interactive request. Visibility completeness can safely withhold availability without exposing which unseen object caused it.
