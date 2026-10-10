# Minimal Action Proposal v1 — permanent shadow

Old A remains **FAIL_STOP_LOCAL_OUTPUT_CONTRACT**. Old B remains **OFFLINE_PROVENANCE_CACHE_EQUIVALENCE_PASS**, on its independent cache branch. Neither is reinterpreted as model planning success.

Model result version: `astra.action_proposal.v1`; existing Broker role: `action_shadow`. The previous `astra.action_shadow.v1` and `astra.action_shadow_candidate.v2` remain supported unchanged. This change does not change the internal `astra.action_chunk_plan.v2`, Supervisor, Owner or physical gates.

## Responsibility and storage

| Model generates | Trusted host binds |
|---|---|
| decision: planned / refused / need_more_evidence | world ID/revision, epoch, observation ID/read_versions |
| waypoint index, move_pose pose, nominal time, prefix dependencies, boundary | actual measured origin, task and target binding |
| termination kind/reason | H=4 ceiling, m=1, K=0, grants_execution=false |
| necessary assumptions, unknowns, refusal/evidence reason | fixed five precondition requirements, source and raw hash |
| optional additional claims with genuine evidence refs | independent current-fact verification receipts; no inferred physical clearance |

All objects are closed and all required properties declared. Host fields at the result, proposal or waypoint levels reject the output; no silent dropping. The host metadata is an input, not a model echo. Refused/need_more_evidence require proposal=null; planned requires a non-null proposal and assumptions.

Pose uses `[x,y,z,qw,qx,qy,qz]`: world metres, pad/grasp-center XYZ and flange quaternion wxyz. Nominal seconds are not actual completion times. The unchanged local v2 validator enforces index, prefix, 2*i seconds, valid quaternion, workspace bounds, 50 mm/0.15 rad maximum step, no-op/microstep rules, and stage-boundary consistency. Four horizon_filled waypoints have no boundary; stage_terminal may shorten to 1–4 with a final explicit boundary. First step always uses the frozen measured origin.

`adapt()` copies model waypoints without numerical modification, inserts only fixed requirement names, and supplies trusted fields. It then runs the bound internal schema and unchanged action validator. It never interpolates, clips, replans or repairs values. `model_proposal.json` and `internal_plan.json` have separate exact-file SHA256 values (canonical sorted JSON with default separators), recorded alongside raw UTF-8 SHA256 and host-context digest in `derived_shadow.json`. `parsed.json` stays the actual model output. Null decisions still produce a null-plan derivation with no action.

The original raw remains a failed-regression input. No conversion of that raw is reported as new-contract success. No server model has seen the new schema in this delivery.

## Preconditions and evidence

All fixed requirements remain `unverified` in the per-waypoint ledger. A requirement name is never evidence. Additional model claims do not fill this ledger.

Machine-checkable `supported_by_input` claims require nonempty references actually sent and present in the answer's evidence envelope. Corresponding checks cover only these captured facts:

- `current_geometry`: target has coarse measured support in a cited current view.
- `target_identity_hypothesis`: target's genuine bound semantic evidence supports a hypothesis, not certified task identity.
- `visibility`: support exists in the cited captured view, not a future viewpoint.
- `measured_join`: only waypoint 1, recorded actual start, not a future join.

Future-scope supported claims and any supported owner admission are rejected. Planned outputs with explicit conflicts are rejected; refusal can describe conflicts. Unknown claims remain unverified. No references are generated to repair missing model citations. Host plan evidence_refs are trusted read dependencies, not fabricated model claims.

A successful current-fact verifier emits a receipt containing exact world/observation hashes, claim index and original refs. Its scope explicitly excludes future waypoint satisfaction. Arbitrary free-text reasoning still requires independent review: these checks are not a semantic entailment model and cannot prove every natural-language assertion. This limitation is recorded, not hidden behind a PASS.

## Execution isolation

Role stays action_shadow. Broker never assigns action_ready, every evidence result/poll carries grants_execution=false and K=0. The derived internal plan remains a private review artifact with a REVIEW_ONLY source. Supervisor rejects it via shadow Broker origin even if task_usable is manually set to pass, and rejects a bare v2 plan without action Broker provenance. No Owner, IK, collision or STOP changes. IK/collision/clearance remain NOT_TESTED; hidden space UNKNOWN_NOT_FREE; owner NOT_GRANTED.

## Next-request preparation

Use `scripts/prepare_action_proposal.py` with the sealed archive root and a NEW output path. It calls only Broker.prepare, allowance=0, does not read credentials and creates no request claim. It verifies W2/real semantic source, public RGB hashes, production strict schemas, frozen launcher/native binary hashes and zero-retry settings. The packet contains a **granted=false** authorization template, no consumed authorization.

A future explicit authorization must identify the new committed source, request/schema hashes and protocol version, create a new independent attempt and claim, and revalidate all sources. At most one action_shadow submission, original model/provider/medium, timeout<=90 seconds, zero client retries/fallbacks; server-internal retries remain UNKNOWN. No E, physical episode, execution, hardware, training or native concurrency is included. This delivery has no automatic-dispatch command.
