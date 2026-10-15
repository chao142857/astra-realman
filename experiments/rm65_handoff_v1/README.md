# RM65 dual handoff V1 — yanglab

**2026-10-15 新任务入口：** [1.1 m Ready Pose / handoff_transfer_only](TRANSFER_READY_20261015.md)。
左右独立初态、两次物理 reset/拾取、四视角与零生成 shadow/执行接口已通过。
该子任务不以完整放置成功为前置；真实请求仍为 0，等待独立新授权。
以下 V1 完整交接与放置的历史结论保留不变。

**Status: P0 layout PASS; P1 partial diagnosis, NOT repaired to the fixed stability criterion; P2 full handoff/place FAIL; P3 four-camera offline loop PASS. Astra generations = 0. Do not request/execute a real model episode yet.**

Independent branch based on `b13164b`. All V0 code, assets, ledgers, failures and videos remain unchanged. Host: yanglab, never ubuntu-robot. No RoboTwin, hardware imports, bridge production requests, physical welds or post-initialization object pose writes.

## Actual deliverables

- `scene_v1.json`: approximate laboratory arrangement, one scene, two RM65+CTAG articulations, 0.72 m base spacing. Dimensions are engineering choices constrained by the existing URDF, not calibration inferred from the photograph. Joint configuration raises elbows and points tools down/inward.
- `evidence/numeric_baseline_01/initial_observation/`: four raw RGB images, raw 2×2 montage (overhead/front/left wrist/right wrist), separate scene preview and camera calibration. The preview and reference photograph are NOT model images.
- `initial_v1.py`: physical left pickup/lift and hold, then stops expert logic. `evidence/offline_episode_01/episode/handoff_initial/` records a tested reset/initialization.
- `evidence/offline_episode_01/`: two fake HTTP decisions with real PhysX execution, 4 image payloads, independent request IDs, raw events, receipts, video and paused-time assertion. PASS means interface only, never handoff success.
- `evidence/gripper_diagnostic_report/`: full time series and figures for the exact original baseline and new controls.
- All failed physical experiments are retained with per-run source snapshots. `raw_archive_manifest.json` gives hashes for lossless gzip copies. Original uncompressed logs remain on yanglab.

## Physical findings (not a model result)

The original `rm65_handoff_v0/evidence/final_baseline_01` still fails at step 5685: right pad penetration 2.3076 mm, approximately 0.740 s valid independent hold after actual left opening. Its scoring is unchanged.

1. Independent right-arm down-facing grasp/5 s hold runs without abort (`right_down_02`). Rotating that held object reproduces pad penetration without a left-arm handoff (`right_rotate_01`), so the fault is not exclusively release timing.
2. CAD/URDF-only FK (`gripper_kinematics_01`) shows that closing from open to a 50 mm gap advances the pad midpoint along local tool Z by **13.69781 mm**. The old sideways receiving target aligned the OPEN midpoint with the cube; the down-facing single-arm script implicitly allowed about 15 mm for closure. These are not equivalent grasp-centering conditions.
3. Changing only the private old-layout receiving target by 13.5 mm while retaining the original controller prevents the former penetration failure for the 5 s observation (`legacy_centered_hold5_01`): bilateral right contact, no left/table contact, maximum pad penetration about 0.355 mm. However reported rigid-body speed remains about 0.033 m/s, exceeding the fixed 0.03 m/s stability criterion. **Script completion is NOT a stable-hold PASS.** Position drift and reported engine velocity are reported separately.
4. Damped mimic tendons alone do not repair the handoff. Centering plus damping also fails the velocity criterion. The independent lower latched torque and higher solver-iteration controls fail penetration protection. None is adopted as the default; the default remains `original` controller and original solver.
5. In the new photo-like layout, a single long held-object move is rejected against the stale cube position in the planner's static collision world. Explicit short numeric moves can carry the left-held object to the candidate handoff region. Right approach paths then encounter inter-arm collision/IK rejection. These are real execution-layer limitations, not Astra failures. OMPL expert reference and raw-RRT-to-numeric replay also did not complete the full handoff.

**P2 remains blocked before successful receiving in the new layout; no complete successful handoff/place video exists.** Failure videos are delivered rather than relabeled. The 10 cm stagger scene is a separately labeled diagnostic, not the final photo layout.

## Reproduce on yanglab

```bash
cd /home/tongji/alex/rm65-dual-handoff-v1-20261014/experiments/rm65_handoff_v1
source runtime.sh
# Every output path must be new. Never overwrite an old run.
"$RM65_PYTHON" offline_tests.py
"$RM65_PYTHON" offline_episode_test.py --output evidence/repro_offline_episode_NEW
"$RM65_PYTHON" right_control.py --output evidence/repro_right_down_NEW
"$RM65_PYTHON" numeric_baseline.py --output evidence/repro_numeric_NEW
"$RM65_PYTHON" numeric_baseline.py --expert --output evidence/repro_expert_NEW
RM65_LAYOUT="$PWD/legacy_layout.json" "$RM65_PYTHON" legacy_centered_control.py \
  --hold-only --output evidence/repro_centered_hold_NEW
"$RM65_PYTHON" evaluate_process.py evidence/repro_centered_hold_NEW
```

The numeric/expert baseline commands reproduce a diagnostic attempt; they are **not certified successful commands**. For source-identical historical runs use their archived `source_snapshot/` and `configuration.json`; snapshots preserve earlier variants and rejected controllers.

## Model vs executor

`action_interface.py` permits world-frame numeric TCP `[x,y,z,w,x,y,z]` using Link6 orientation, or gripper opening fraction, with sequential/parallel groups and omitted-arm hold. TCP is the measured midpoint of inner pad faces; it changes with finger configuration. No automatic object-centered compensation, grasp skill, target snap or task-aware rerouting exists in the public executor.

The public executor chooses closest IK and fixed cubic joint interpolation, checks the entire shared collision world, then advances real physics. Expert OMPL and the private RRT waypoint script are engineering references only. Inference pauses physics; wall and simulation times are distinct. Collision/contact GT is private safety/evaluation data and never model feedback. Only robot measured state, four calibrated RGB, task and two recent raw proposal/receipt pairs enter the model context.

Additional shared-physics test `interface_smoke.py --output evidence/NEW` PASS: both TCPs move upward 5 mm in overlapping shared steps 550–775; position residuals approximately 0.032 mm each. Parallel gripper commands PASS; invalid parallel group is rejected before any physics step. This does not prove handoff coordination.

Seven protocol tests PASS (including malformed JSON/events, auth, parameter drift, forbidden real dispatch, image/GT validation and timeout/cancel). Two-step fake Bridge + physics loop PASS. This is not evidence of Astra ability.

`run_episode.py --real` and the real adapter deliberately fail closed. A future run needs physical baseline acceptance, production preflight, a separate authorization record and a real budget gate. No current command can spend an old authorization. **Suggested future budget only after those prerequisites: one handoff_only episode, at most 16 decisions. No authorization is requested while the physical baseline remains blocked.**

## Versions / fixed safety

Python/dependencies and assets are reused from `runtime.sh`: SAPIEN 3.0.0b1, mplib 0.2.1, numpy 1.26.4, scipy 1.10.1, trimesh 4.4.3, toppra 0.6.3. The original asset manifest is checked on every simulator import. No dependency upgrade. dt=0.004 s, gravity and real dynamic cube/contact remain enabled. Original 2 mm safety stop is unchanged. `process_criteria_v1.json` was saved before any claimed complete V1 success; no threshold was relaxed. Evaluation is independent and reports actual continuous duration, including zero.
