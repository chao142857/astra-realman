# Astra / RealMan snapshot — 2026-10-05

Source: `yanglab:/home/tongji/alex/astra_realman_harness`.
Intended destination: `RoboticsTJZNFY/DiffusionPolicy_Team`, directory `astra_realman_harness/` on a separate branch.

The harness files are copied byte-for-byte; no control behavior was changed and no robot command was sent during archiving. Capture occurred while the operator’s last run was active. Logs and camera images remain on the workstation and are not included. Authentication tokens, .env files and caches are excluded. `SNAPSHOT_SHA256.json` records the copied file hashes; the older harness FILE_MANIFEST.json is preserved as historical content.

Includes official Codex Astra backend and Mac bridge, three/four-view runners, three-view history-five runner, adapters, schemas, configs, tests and existing documentation. External RealMan SDK/lab code and workstation Python environment are referenced by existing paths, not vendored. Authentication must be provisioned separately. This is an experiment code archive, not a portable environment or a new safety certification.
