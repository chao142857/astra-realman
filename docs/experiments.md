# Experiments and source navigation

[Project overview](../README.md) · [Reproduction](reproduction.md)

The five branches retain different research implementations. Results below distinguish real hardware, simulator physics, geometry evaluation, and synthetic/Stub execution. Original reports remain unchanged.

## RealMan V17 / V19

**Work and result.** A multimodal model proposed arm/gripper actions through a GUI, bounded history, inverse kinematics, and measured execution feedback. On October 18, 2026, the onsite operator confirmed one complete V17 banana pick–handoff–place: **33 model requests, 1176.332 seconds**. The model's completion flag is recorded separately from that confirmation.

**Failure.** V19 did not complete the handoff. The right arm never established a grasp; repeated alignment/descending proposals and IK rejections did not converge. The two runs were not a controlled repeatability comparison.

**Code — `realman/v17`:** [GUI](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/astra_gui.py), [model backend](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/codex_astra_backend.py), [dual-arm coordinator](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/parallel_arms.py), [V17 prompts](https://github.com/chao142857/astra-realman/tree/realman/v17/astra_realman_harness/prompts/banana_handoff_v17).

**Evidence:** [V17 manifest](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/docs/V17_SUCCESS_SNAPSHOT_20261018.md) · [V17/V19 lightweight records and analysis](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/docs/banana_v17_v19_light_20261018/README.md). The homepage GIF shows the V17 successful execution at 3× playback, as confirmed by the project owner. The full raw-input and run archive remains separately retained.

## Spatial A/B/C

**Work and result.** Compared A (multi-view RGB), B (estimated geometry), and C (oracle geometry), with independent geometry scoring and recorded model pilots. In the isolated six-scene B-v2 evaluation, legal-path retention increased **20/214 → 206/214**; legal yaw-pose retention increased **0/58 → 58/58**. Neither B version falsely accepted the sampled 1376 illegal paths.

**Failure.** B-v2 falsely accepted **182/13172 illegal yaw poses** because of missing obstacles. Only 58 of its 240 accepted yaw candidates were legal (24.17%). These are finite geometry samples, not an improvement in model task success; B-v2 validation made zero model requests. Oracle geometry is an evaluation reference.

**Code — `research/spatial`:** [evaluation package / CLI](https://github.com/chao142857/astra-realman/tree/research/spatial/experiments/spatial_input_eval_v0/spatial_eval), [B-v2 geometry](https://github.com/chao142857/astra-realman/tree/research/spatial/experiments/spatial_input_eval_v0/lab/b_v2), [frozen A/C dispatcher](https://github.com/chao142857/astra-realman/tree/research/spatial/experiments/spatial_input_eval_v0/lab/astra_ac).

**Evidence:** [Pilot 01 analysis](https://github.com/chao142857/astra-realman/tree/research/spatial/experiments/spatial_input_eval_v0/evidence/pilot01_analysis_20261013) · [Pilot 02 continuation](https://github.com/chao142857/astra-realman/blob/research/spatial/experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01/CONTINUATION_REPORT.md) · [B-v2 report](https://github.com/chao142857/astra-realman/blob/research/spatial/experiments/spatial_input_eval_v0/evidence/b_v2_20261014/REPORT.md).

## Persistent World and action history

**Work and result.** Maintained geometry, semantic object bindings, action chunks, provenance and post-action updates across decisions. The October 11 simulation comparison recorded ordinary FULL_SYSTEM stopping at its action contract (K=9, 284.786 s), while ordinary VANILLA_ASTRA completed (K=11, 276.283 s).

**Failure.** The occluded FULL_SYSTEM run stopped on inference failure (K=7, 225.363 s); the paired occluded vanilla run was not yet run in the handoff record. This finite comparison does not establish an overall advantage or a physical-robot result.

**Code — `realman/v17` retains this earlier line:** [world head and RGB-D updates](https://github.com/chao142857/astra-realman/tree/realman/v17/astra_realman_harness/platform_v1/research), [simulation comparison entry](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/scripts/run_persistent_chunk_pair_episode.py). Its presence in this branch does not mean that all research components participated in V17.

**Evidence:** [October 11 handoff and comparison](https://github.com/chao142857/astra-realman/blob/realman/v17/LAB_CODEX_HANDOFF_1011.md) · [semantic-binding evidence](https://github.com/chao142857/astra-realman/tree/realman/v17/astra_realman_harness/docs/persistent_semantic_binding_v1).

## RM65 dual-arm simulation

**Work and result.** Developed simulation interfaces, numeric action chunks, contact checks, and grasp/release diagnostics. D4's original **38 action groups** completed in sequential replay, preserving repeated same-arm targets; parallel same-arm conflicts were rejected.

**Failure.** The original D1 contact case stopped at **2.191056 mm** penetration. Separate grasp/release and empty-hand D4 controls did not establish a complete model-driven pick–handoff–place. Here “physics” and historical “real Astra” refer respectively to simulator dynamics and actual model requests, not physical RealMan hardware.

**Code — `research/rm65`:** [episode entry](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/run_episode.py), [action-chunk contract and scheduling](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/chunk_protocol_v2_1.py), [simulation implementation and diagnostics](https://github.com/chao142857/astra-realman/tree/research/rm65/experiments/rm65_handoff_v1).

**Evidence:** [D4/contact replay](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/INTERFACE_REPAIR_YANGLAB_20261017.md) · [first full-task model episode](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/FULL_TASK_FIRST_REAL_20261016.md) · [original D4 diagnosis](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/DECISION4_DIAGNOSIS_20261015.md).

## ASPIRE Phase 0–2B

**Work and result.** Phase 0 established replay/contracts; Phase 0.5 connected native CPU CAP/MCP; Phase 1A prepared live observation interfaces; Phase 1B tested SAM3 and geometry on a sealed image; Phase 2A/2B explored GPU planning and execution feedback. Official SAM3 and native HTTP returned matching first-five masks (IoU 1.0). Phase 2B passed arm-only GPU planning into Stub execution, including cancellation and feedback checks.

**Failure.** Contaminated depth produced a **1.519 m** raw OBB major axis, so segmentation success was not qualified 3D localization. World/TCP validation and full assembly collision geometry remained unresolved. GPU/Stub results used **ARM_ONLY_DIAGNOSTIC + SYNTHETIC** bases, without complete grippers/wrist cameras or physical transport. This track was not a completed real-robot deployment.

**Code — `develop/aspire`:** [Phase 0 replay](https://github.com/chao142857/astra-realman/tree/develop/aspire/aspire_realman_phase0/src), [native adapter](https://github.com/chao142857/astra-realman/tree/develop/aspire/aspire_realman_phase05/src), [observation interfaces](https://github.com/chao142857/astra-realman/tree/develop/aspire/aspire_realman_phase1a/src), [perception/geometry tools](https://github.com/chao142857/astra-realman/tree/develop/aspire/aspire_realman_phase1b/tools), [planning/execution](https://github.com/chao142857/astra-realman/tree/develop/aspire/aspire_realman_phase2a/src).

**Evidence:** [Phase 0](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase0/VALIDATION.md) · [Phase 0.5](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase05/README.md) · [Phase 1A](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase1a/VALIDATION.md) · [Phase 1B SAM3/geometry](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase1b/README.md) · [Phase 2A](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase2a/README.md) · [Phase 2B](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase2a/PHASE2B.md).
