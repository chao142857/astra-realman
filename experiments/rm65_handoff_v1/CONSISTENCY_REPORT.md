# RM65 holding / collision consistency audit — offline archive

**yanglab became unreachable.** The original holding audit below was independently recomputed from byte-identical local raw archives. New physics observations are preserved as `offline_archive/server_observed_summary_NOT_RAW.json`, explicitly a summary of tool output, not recovered raw logs or videos. All new full server artifacts remain pending retrieval. No complete archive of the new physical episodes or independent regrading is claimed.

Base: `89f1d95`; current four-view `scene_v1.json`, original motor controller, original PhysX settings and 2 mm protection. Real Astra requests: **0**. Historical results and historical scores are read-only.

## Strict original phase

Source: `legacy_centered_hold5_01/physics.jsonl.gz`, exact `right_independent_hold` phase, steps 5711–6960: 1250 consecutive post-step samples, dt=4 ms. The adjacent-difference comparison uses 1249 exactly aligned intervals (reported velocity at row i vs `(p_i-p_{i-1})/dt`); full-phase engine statistics and the old score retain all 1250 rows. The phase starts after the actual left pad gap exceeds 70 mm; no records inside the phase are discarded. First-to-last timestamp span is 4.996 s; the 1250 simulated steps cover 5 s.

| Measure | Exact phase result |
|---|---:|
| PhysX reported world COM speed, median / mean / maximum | 33.473 / 33.513 / 33.961 mm/s |
| Adjacent world COM position difference speed, median / mean / maximum | 0.00838 / 0.02216 / 0.14771 mm/s |
| World XYZ position ranges | 0.04193 / 0.06530 / 0.00535 mm |
| Maximum cube displacement relative to measured right TCP | 0.000917 mm |
| Maximum relative orientation change | 0.000533 degrees |
| Right bilateral contact samples | 1250/1250 |
| Left / table contact samples under original log impulse cutoff | 0 / 0 |
| Maximum pad penetration | 0.35525 mm |

The cube actor origin and center of mass coincide (independently checked local COM transform: translation zero, identity rotation). Both quantities are sampled consecutively after the same synchronous `scene.step()`; there is no intervening physics step. Thus this discrepancy is not explained by a different reference point or dt. Integrating reported velocity over the matching intervals predicts approximately [-98.56, -101.54, +89.49] mm; observed displacement is [+0.04160, +0.06528, -0.00496] mm. Relative grip pose shows retained physical contact, not sustained sliding.

Actual runtime: SAPIEN 3.0.0b1; PhysX `105.1-physx-5.3.1.patch0`; TGS enabled, PCM and friction-every-iteration enabled, gravity -9.81 m/s²; cube and both articulations 10 position / 1 velocity iterations. The original score still **FAILS** its 30 mm/s reported-speed criterion. No threshold, smoothing, record filtering or regrading replaces that result.

PhysX's [5.3.1 body API](https://nvidia-omniverse.github.io/PhysX/physx/5.3.1/_api_build/class_px_rigid_dynamic.html) identifies the reported linear velocity as COM velocity. The newer official [solver documentation](https://nvidia-omniverse.github.io/PhysX/physx/5.8.0/docs/Simulation.html#solver-iterations) explains that transform integration and reported post-solve velocity can differ under constraints, including TGS. The exact installed build's internal motion-velocity buffer was not instrumented, so the observed discrepancy is consistent with solver sampling semantics, rather than proof of a specific engine defect.

A separately proposed retention criterion would require a fixed 5 s window, bilateral right support, actual left release/no supporting left/table contact, relative translation drift <=2 mm, relative rotation drift <=2 degrees, no drop and unchanged 2 mm penetration protection. For a 50 mm cube, 2 degrees displaces a corner by about 1.5 mm, below the existing 2 mm contact tolerance; translation/rotation tolerances concern retention, not world motion speed. This is a proposal, not a replacement for the frozen historical criterion or authorization to report new benchmark PASS.

## First rejected archived RRT waypoint

`rrt_numeric_replay_01/group_070`, zero-based private waypoint 51, physical step 18760 before rejection:

- FK from the known joint sample and requested flange differ by about **1.146 micrometres**, with negligible quaternion difference.
- FK at the logged actual joint configuration matches measured Link6 within **0.245 micrometres** and **1.35e-6 radians**.
- The constant-vs-current finger-dependent TCP offset accounts for approximately **1.146 micrometres**, not a millimetre-scale frame error.
- Pure CLIK succeeds, joint wrapping/limits pass, and a known-waypoint seed also reaches the requested pose. Collision-gated IK correctly rejects it: **R__ctag_Left_1_Link vs L__Link6** is a real FCL conflict at the known configuration.

Therefore the first RRT refusal is not an FK/world/TCP round-trip failure. The private route contained an invalid dense sample; it must not be treated as a valid reference simply because native RRT returned “Exact solution.” The public executor now logs pure IK success, limit validity and specific collision pairs separately, without changing the supplied goal.

## Actual erroneous refusal and fix

A matched precheck uses the unchanged left TCP goal `[0.36, 0.20, 0.102, 0, 1, 0, 0]`:

- Old static-object representation first reports `L__ctag_Right_2_Link / target_cube` at interpolation index 94.
- With a contact-established holder, the collision-only FCL cube follows candidate holder FK using the measured relative transform. The entire same path has no collision.
- The public numeric executor physically executes this exact goal; the freely simulated cube moves from approximately [0.36120, 0.000060, 0.16434] to [0.36063, 0.19991, 0.09992] m.

Only planning collision objects change pose. There is no PhysX weld, object pose write or forced trajectory. The body remains free, gravity/contact driven. Both robots, non-pad links, table/stands and carried-object/environment collisions are checked; the original pad contact exceptions and 2 mm physical stop remain. Ownership is refreshed from actual contact state and release commands for each action. This private representation is excluded from model context.

Receiving-centering is calculated from robot CAD opening-dependent pad midpoint and the supplied tool quaternion (`gripper_centering.py`). The open-to-50-mm-gap local advance is rotated into world coordinates. A fixed world Y shift is not a public controller rule; no model target is compensated or snapped automatically.

## Current-layout replay

The validated candidate uses left TCP `[0.36, -0.20, 0.102, 0, 1, 0, 0]` and right quaternion `[-0.5,-0.5,0.5,-0.5]`. Its approach, receipt and hold are executed by the same closest-IK/cubic numeric interface the model would use. Private expert candidate selection is not delivered to the model.

- `replay_01`: dense private RRT reference refused before right motion. Some routes truly collide; others exceed the existing TCP workspace. Its `earliest_failed_phase` inherited the previous physical phase; attempted failing stage was **right_approach**, step 3716. Original result is retained; this paragraph is the metadata correction.
- `replay_02`: approach, right receiving, left release, 5 s independent right hold, exit and left retreat complete. Stops at **right_to_place**, step **9547**, before executing a target without a valid IK solution. No generic gripper-instability claim follows from this failure.
- `replay_03`: same successful handoff/exit, then explicit reorientation. Physical **PAD_PENETRATION** stops the rotation at step **9628**. This is a specific rotation/contact failure; the threshold is unchanged.
- `replay_04`: keeps the grip orientation, attempts an explicit arc instead of the inward diagonal. Final raw result and video must be read before claiming its outcome.

Reproduction on yanglab:

```bash
cd /home/tongji/alex/rm65-handoff-consistency-20261014/experiments/rm65_handoff_v1
source runtime.sh
"$RM65_PYTHON" collision_fix_smoke.py --output evidence/consistency_20261014/REPRO_NEW
"$RM65_PYTHON" physical_replay.py --output evidence/consistency_20261014/REPLAY_NEW
```

Every output path must be new. The current replay command describes the latest explicit engineering route (outcome not yet read); per-run source snapshots preserve each earlier variant. These commands spend zero model requests. The real bridge and real model gate remain unchanged.

## Offline archive status / retrieval boundary

- Local strict-phase recalculation: `evidence/consistency_20261014/stability_aligned_local/summary.json`, `exact_phase.csv`, `phase_audit.svg`.
- Original RRT first failure and reconstructed known joint sample: `offline_archive/`. Original source hashes verified against the local frozen files; source files were not changed.
- New server observations: `offline_archive/server_observed_summary_NOT_RAW.json`. These are explicitly transcribed result observations, not replacements for the actual server artifacts.
- Pending on yanglab: full `roundtrip/`, `carry_smoke/`, `candidates/`, `replay_01`–`replay_04` raw events/physics/video/source snapshots; especially the unread result of replay_04. No new full physical episode is independently scored locally yet.
- Prepared but not run after connection loss: carried-object/table negative control, model-input private-state exclusion control and final regression tests. The only accepted physical fix evidence so far is the matched carry_smoke server observation; no claim that the whole new executor acceptance is complete.

When yanglab returns, retrieve those directories **read-only** first, verify their source snapshots/configuration, independently evaluate recorded hold/place phases and read the first stopped step. Preserve every attempt. Do not launch another replay just to obtain prettier results. No real bridge or generation request is involved.
