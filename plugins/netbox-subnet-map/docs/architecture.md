# Architecture

NetBox owns infrastructure truth and the rules that protect it. The plugin owns the operational presentation of that truth.

`SubnetMapAssembler` builds one authoritative read model consumed by the Grid, Table, and Inspector. It does not persist inventory.

Allocation follows: Cell → Inspector → Native Quick Add → `IPAddressForm` → NetBox validators → transaction → post-save permission check → changelog → authoritative re-read.

Cell color is never write authorization. `allocation_state` (`candidate`, `blocked`, or `unknown`) is presentation eligibility. POST re-runs authoritative state; browser input is untrusted. The plugin has no service/API writer token and no inventory model.
