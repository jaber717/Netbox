# CMDB audit

Final classification: **PARTIAL**. CMDB is excluded from Production v1.

## What exists on LXC 9001

- Five Choice Sets: data source, lifecycle, support level, device criticality,
  and a warehouse stock classification.
- Sixteen Custom Fields covering criticality, provenance, lifecycle, support,
  EOS/EOL, software version, warranty/purchase dates, cost center and warehouse
  metadata.
- `ActiveCMDBDeviceValidator`, registered for `dcim.device`.
- A native Custom Script that reports device completeness and stale `last_seen`.
- The unrelated `inventory_monitor` plugin is loaded in the lab.

The active validator requires tenant, role, serial, criticality and data source
for active non-passive devices. Patch panels, ODFs and PDUs are exempt. The
report is role-aware for the same passive roles and evaluates ownership through
native Contact Assignments.

## What was not found

- No `SoftwareVersionOwnershipValidator` implementation.
- No implemented `depends_on`, `redundancy_peer`, or `managed_by_vendor`
  relationships. NetBox 4.6.9 also has no `Relationship` model in `extras`.
- No dedicated CMDB acceptance suite.
- No located `phase-2.0-cmdb-foundation.md` file.
- No proof that the lab's warehouse fields or `inventory_monitor` are suitable
  for the production product.

## Release decision

The field/validator/report work is useful but unverified. It is preserved under
`experimental/cmdb/` as a future-phase reference and is not copied, registered,
or bootstrapped by `install.sh`. `features.cmdb: true` is deliberately rejected
by configuration validation. Productionizing CMDB requires an idempotent native
bootstrap plus the explicit acceptance suite described in the project brief.
