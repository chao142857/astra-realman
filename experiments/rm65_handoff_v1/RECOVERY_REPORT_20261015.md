# RM65 evidence recovery and final stopped step — 2026-10-15

**All pending server evidence has now been retrieved and verified. The two consistency blockers are resolved/diagnosed, but the full handoff-and-place engineering baseline still FAILS. No Astra generation request was made.** This addendum supersedes the pending-retrieval status in `CONSISTENCY_REPORT.md`; it does not change any historical result or score.

## 1. Holding meaning, using original scores and exact raw phases

The original `legacy_centered_hold5_01` audit is unchanged: reported world speed approximately 33.5 mm/s versus adjacent pose-difference speed 0.022 mm/s mean, relative position drift 0.000917 mm. Original reported-speed criterion remains FAIL.

The retrieved `replay_02`, `replay_03`, `replay_04` and corrected replay share the same deterministic handoff prefix. Their exact `right_independent_hold` phase is steps **6815–8064**, 1250 post-step samples / 5 simulated seconds:

| Measure | Result |
|---|---:|
| Right bilateral support | 1250/1250 samples |
| Left/table supporting contact under original log impulse cutoff | 0/0 samples |
| Maximum relative object/right-TCP translation drift | **0.004466 mm** |
| Maximum relative rotation drift | **0.001920 degrees** |
| Object world XYZ position ranges | 0.001848 / 0.004247 / 0.011966 mm |
| Reported world speed mean / maximum | 41.201 / 43.595 mm/s |
| Adjacent pose-difference speed mean / maximum | 2.873 / 2.930 mm/s |
| Maximum pad penetration within the hold phase | **0.489642 mm** |

World pose-difference speed includes small oscillatory world motion; it is not cumulative sliding. Relative retention and world motion are reported separately. No smoothing or velocity threshold changes were used. SAPIEN 3.0.0b1 / PhysX 5.3.1 TGS, original 10/1 solver iterations, original controller, current four-view layout and the original 2 mm physical protection are verified unchanged.

The **unmodified** `evaluate_process.py` and `process_criteria_v1.json` were SHA-checked and run independently, writing only separate analysis files. Every full-task result remains **FAIL**: reported-speed hold criterion not met and no stable placement. `replay_03` additionally fails pad penetration protection. No real Astra decision or capability score is inferred from these engineering attempts.

Sources: `evidence/recovered_yanglab_20261015/independent_analysis/`, `evidence/corrected_evidence_retrieved_20261015/hold_audit/`, and the independent original-score JSONs alongside them.

## 2. Actual false refusal versus correct refusal

**False refusal fixed:** same left TCP `[0.36, 0.20, 0.102, 0, 1, 0, 0]`, same original controller. The old collision world leaves the held cube at its starting position and reports `L__ctag_Right_2_Link / target_cube` at interpolation index **94**. A collision-only FCL representation following the contact-established holder's candidate FK removes this stale geometry. The unchanged goal physically executes, with a free dynamic cube. There is no PhysX weld or post-initialization object pose write.

**Safety retained, actual regression PASS:** a held-object/table negative control is rejected as `IK_REJECTED_COLLISION`, explicitly `target_cube / table`, with **zero physics steps** and no target correction. Private holder/relative-object data is absent from the public model context. Seven fake-Bridge protocol tests PASS, zero real generation.

Evidence/video: `evidence/safety_evidence_retrieved_20261015/carry_safety_regression_20261015/`.

**Correct original refusal:** archived `rrt_numeric_replay_01/group_070` has approximately 1.146 µm FK/request translation discrepancy; pure CLIK succeeds and joint limits pass. The known joint configuration actually conflicts in FCL: **R__ctag_Left_1_Link / L__Link6**. Its original refusal must not be relabeled a frame or grasp-offset failure. The complete recovered FK/IK audit is in `evidence/recovered_yanglab_20261015/consistency_20261014/roundtrip/audit.json`.

Receiving centering is computed from robot CAD pad-midpoint motion and the tool orientation, not a generic fixed world-Y shift. It remains private reference-script logic; the public executor never snaps or compensates a model's proposed target.

## 3. Physical replay and exact earliest failure

| Attempt | First stopped point | Meaning |
|---|---|---|
| replay_01 | Before right approach; step 3716 | Dense private-route check detects actual inter-arm collision or unchanged workspace-box violation. Previous phase metadata is retained with a separate erratum. |
| replay_02 | group_012, step **9547**, 38.188 s | Handoff, independent hold, right exit and left retreat completed. Next placement TCP fails the fixed IK process before execution. |
| replay_03 | group_012, step **9628**, 38.512 s | Explicit receiving-to-downward rotation partially executes, then pad penetration reaches **2.63609 mm** and the original protection stops it. |
| replay_04 | group_014, step **10042**, 40.168 s | Private reference arc had a flange/TCP sign error; this is a reference-script bug, not model failure or evidence of global unreachability. |
| corrected_replay_20261015 | group_015, step **10338**, **41.352 s** | Corrected first arc waypoint physically executes. Next placement TCP fails the fixed IK process, **not executed**. No drop, inter-arm contact or pad-penetration abort precedes it. |

The recovered `replay_04` snapshot exposed my reference-arc error: the forward conversion incorrectly used `p_flange - R @ tcp_local`. Correct is **`p_tcp = p_flange + R @ tcp_local`**, inverse `p_flange = p_tcp - R @ tcp_local`. The old first target jumped by approximately **430.481 mm** along Y. This was corrected only in the private reference geometry. The public executor and model proposals are not modified.

Offline round-trip checks use the recovered actual robot state, reconstruct the old erroneous target within 1.2e-8 m and verify the corrected arc's endpoint/inverse transform to <1e-12 m. One new physical run verifies this concrete correction; all older attempts remain intact.

The current earliest failure is right TCP (metres / world wxyz):

```json
[0.3691557776901396, -0.06927625568687495, 0.13968121364937797,
 -0.5, -0.5, 0.5, -0.5]
```

The fixed collision-gated IK search found no valid solution, and the extra current-seed CLIK diagnostic did not converge. No candidate was available for that diagnostic's collision test; an empty collision-pair list here is **not** proof that all possible branches are collision-free. This is a specific execution-layer proposal refusal. It does not prove global unreachability, gripper instability, or anything about Astra.

Latest video: `evidence/corrected_evidence_retrieved_20261015/corrected_replay_20261015/execution.mp4`. Successful handoff/hold observations and failure videos of every earlier variant are also retained.

## Archive and reproduction

`evidence/retrieval_manifest_20261015.json` records **856 verified server files**, **360 verified source-snapshot files**, and **45 byte-identical lossless raw-stream gzip archives**. Original uncompressed raw logs remain on yanglab and in the local retrieval checkout; Git carries reversible gzip copies. All four-view image hashes, current layout, original controller and solver configuration are checked. No historical log, result, ledger, original criterion or 2 mm threshold was edited.

The corrected reference code is committed as `0e8d773`, used on yanglab in an independent worktree. Its command is reproducible but currently reproduces a failed placement attempt, not an accepted full baseline:

```bash
cd /home/tongji/alex/rm65-handoff-corrected-replay-20261015/experiments/rm65_handoff_v1
source runtime.sh
"$RM65_PYTHON" physical_replay.py --output evidence/REPRO_NEW_DIRECTORY
"$RM65_PYTHON" collision_fix_smoke.py --output evidence/SAFETY_NEW_DIRECTORY
```

This delivery completes retrieval, consistency checks, the concrete coordinate correction and its validation. There is no accepted complete placement baseline and no real-model authorization request. Further work would have to address the specific remaining IK/placement route, with the current failures preserved.
