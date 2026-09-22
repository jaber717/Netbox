# Optional offline mode

Connected RHEL 9.x is the supported golden path. `build/build-offline-bundle.sh`
retains the previous deterministic RPM/wheel/source bundle architecture and now
uses enabled RHEL 9.x repositories dynamically, verifies the pinned NetBox
archive, and builds the vendored Subnet Map wheel.

Offline bundles are generated release artifacts. RPM repositories, wheels,
archives and private checkpoints must never be committed to Git.

This RC has not re-executed the offline build or offline installation. Do not
describe it as production-validated until a registered RHEL 9.x build host and
a disconnected clean target both pass `install.sh` and `verify.sh`.
