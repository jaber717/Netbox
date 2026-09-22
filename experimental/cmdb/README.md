# CMDB prototype preservation

This directory preserves the useful, read-only-reviewed parts recovered from
LXC 9001. It is not an installation input and is not production-ready.

- `cmdb_device_validator.py`: conditional active-device completeness policy.
- `cmdb_completeness.py`: role-aware native Custom Script report.
- `bootstrap-reference.yml`: names/types of the observed native objects.

Do not enable these files directly. A future CMDB phase must add an idempotent
bootstrap, ownership semantics, relationships and dedicated acceptance tests.
