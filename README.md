# Astra × RealMan

**An experimental record of real-robot manipulation, spatial reasoning, and embodied-system integration.**

[English](README.md) · [简体中文](README_CN.md) · [Repository](https://github.com/chao142857/astra-realman)

> **Project status — research archived (October 2026).** Active work on this line has concluded. This repository preserves working integrations, experimental branches, failure analyses, and reproducibility records; it is **not** a validated, general-purpose robot manipulation system. The final branch consolidation may still be in progress; the commit-pinned links below work independently of branch renaming.

## Overview

Astra × RealMan explores what happens when a multimodal decision backend is placed inside a real robotic manipulation loop. The project connects observations and robot state to structured action proposals, host-side validation, robot/simulator execution, and post-action feedback. Over October 2026, the work expanded from a basic RealMan harness to history-aware operation, spatial input experiments, dual-arm simulation, a real-robot handoff attempt, and a separate ASPIRE integration track.

The implementation and experiment harness were developed by [@chao142857](https://github.com/chao142857). **Astra, ASPIRE, SAM3, cuRobo, RealMan hardware, and vendor SDKs are external technologies**, not models or products developed in this repository.

### Research questions

- **Perception and grounding:** What spatial evidence should a general model receive—multi-view RGB, estimated geometry, or an oracle reference—and how should missing or unreliable geometry be represented?
- **Closed-loop execution:** How should decisions, action chunks, history, object state, inverse kinematics, collision checks, and feedback interact without concealing failures?
- **Real-world transfer:** Which parts of an offline or simulated result remain valid when calibration, end-effectors, contact dynamics, timing, and hardware interfaces enter the loop?

These are related lines of investigation, **not one fully integrated, end-to-end system that was demonstrated to work in all settings**.

## Key results — with their limits

| Track | Evidence recorded | What it **does not** establish |
| --- | --- | --- |
| **Real robot / V17** | **One operator-confirmed complete banana pick–handoff–place** on the RealMan dual-arm setup, October 18, 2026. The retained run reported `MODEL_DONE`, **33 client requests**, and **1,176.3 s** elapsed. | No repeatability estimate, autonomous physical scoring, or reliable success rate. The later V19 run did not finish. |
| **Spatial input evaluation** | Experiments with **A: multi-view RGB**, **B: estimated geometry**, and **C: oracle geometry**. In the isolated six-scene B-v2 geometry test, legal path retention improved **20/214 → 206/214**, but the estimate also falsely accepted **182 illegal yaw poses**. | Geometry metrics alone do not demonstrate improved Astra task success. The B-v2 validation made **no Astra model requests**. Oracle inputs are not deployable perception. |
| **RM65 dual-arm simulation** | Physics/interface tests, a **38-group D4 sequential-action replay**, grasp/release checks, and failure witnesses. | A full model-driven pick–handoff–place was **not completed** in this track; an original D1 configuration still stopped at **2.191 mm** contact penetration. |
| **Persistent World** | Geometry-first world representation, semantic binding, history/provenance validation, action chunks, and post-action updates. | The October 11 single-run comparison did **not** show an overall advantage: the ordinary full-system run failed, while the ordinary vanilla run passed. |
| **ASPIRE perception** | Official SAM3 inference and native HTTP parity on a sealed RGB image; the first five returned masks matched the reference masks (**IoU 1.0**). | Qualified 3D localization was **not achieved**: contaminated depth produced an implausible **1.519 m** raw OBB major axis. World/TCP validation remained incomplete. |
| **ASPIRE planning** | Native CAP/MCP to GPU planning and a Stub execution/feedback loop passed under **`ARM_ONLY_DIAGNOSTIC + SYNTHETIC`** conditions. | This was **not** a complete robot assembly or hardware-execution result. Full collision-geometry evidence and physical transport were unresolved; the real-motion dispatcher still rejected execution. |

The table separates physical observations, model requests, simulation, oracle-assisted evaluation, and synthetic/Stub diagnostics. A `PASS` in one category must not be treated as success in another.

## Repository entry points

The following names are the **five intended entry branches after consolidation**. The SHA links point to actual historical snapshots, including while the consolidation is pending. `main` retains the original October 5 code baseline while its top-level documentation serves as the project index.

| Entry branch | Purpose | Pinned snapshot |
| --- | --- | --- |
| [`main`](https://github.com/chao142857/astra-realman/tree/main) | Original v0.1 RealMan integration baseline and archive navigation | [`22bfb2e5`](https://github.com/chao142857/astra-realman/tree/22bfb2e549e6ca98b741ba84f254d4c1bbe66225) |
| [`realman/v17`](https://github.com/chao142857/astra-realman/tree/realman/v17) | Real-robot GUI, V17 successful-run snapshot, V19 record | [`3d765ab9`](https://github.com/chao142857/astra-realman/tree/3d765ab9cd8a41fe226db1fd7ea507998752440b) |
| [`research/spatial`](https://github.com/chao142857/astra-realman/tree/research/spatial) | A/B/C spatial inputs, Pilot studies, estimated geometry | [`6484545b`](https://github.com/chao142857/astra-realman/tree/6484545bb3d760a0753cc33f10e6e4f35e0acb5a) |
| [`research/rm65`](https://github.com/chao142857/astra-realman/tree/research/rm65) | RM65 simulation, contact diagnostics, action-chunk execution | [`c3330268`](https://github.com/chao142857/astra-realman/tree/c3330268e6288ebde1ea232c56fd29f00c80032b) |
| [`develop/aspire`](https://github.com/chao142857/astra-realman/tree/develop/aspire) | ASPIRE integration through offline Phase 2B; not a completed real-robot port | [`c7597fc2`](https://github.com/chao142857/astra-realman/tree/c7597fc27c8744044741888a9e6fff6e60a891cf) |

The original 75 remote branch heads are intended to be retained as immutable-commit references via namespaced archival tags before old branch names are removed. **Branch deletion should not occur until remote tags and an independently restorable Git backup have been verified.** This does not, by itself, back up untracked workstation data or large external evidence files.

## Timeline and primary evidence

| Period (2026) | Stage | Primary record |
| --- | --- | --- |
| Oct 5–6 | Initial real-robot harness | [Original baseline README](https://github.com/chao142857/astra-realman/blob/22bfb2e549e6ca98b741ba84f254d4c1bbe66225/README_CN.md) |
| Oct 7–9 | History, dual-arm scheduling, full PnP engineering, simulator/Stub experiments | [PnP engineering snapshot](https://github.com/chao142857/astra-realman/tree/d5757f232d0886b1736460d8d2b5218d79f855ac) |
| Oct 9–11 | Persistent World and action chunks | [October 11 handoff / A–B limits](https://github.com/chao142857/astra-realman/blob/431f112c80f13a997a8ac1df81cbc3644c1d30ae/LAB_CODEX_HANDOFF_1011.md) |
| Oct 12–14 | Spatial inputs, Pilot 01/02, B v2 | [Pilot 02 continuation](https://github.com/chao142857/astra-realman/blob/6484545bb3d760a0753cc33f10e6e4f35e0acb5a/experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01/CONTINUATION_REPORT.md) · [B-v2 failure analysis](https://github.com/chao142857/astra-realman/blob/6484545bb3d760a0753cc33f10e6e4f35e0acb5a/experiments/spatial_input_eval_v0/evidence/b_v2_20261014/REPORT.md) |
| Oct 14–17 | RM65 physics and dual-arm execution | [Contact / sequential-action acceptance](https://github.com/chao142857/astra-realman/blob/c3330268e6288ebde1ea232c56fd29f00c80032b/experiments/rm65_handoff_v1/INTERFACE_REPAIR_YANGLAB_20261017.md) |
| Oct 17–18 | Real-robot V17 and V19 | [V17 evidence manifest](https://github.com/chao142857/astra-realman/blob/3d765ab9cd8a41fe226db1fd7ea507998752440b/astra_realman_harness/docs/V17_SUCCESS_SNAPSHOT_20261018.md) · [V17 / V19 separate accounting](https://github.com/chao142857/astra-realman/blob/3d765ab9cd8a41fe226db1fd7ea507998752440b/astra_realman_harness/docs/banana_v17_v19_light_20261018/README.md) |
| Oct 19–21 | ASPIRE Phase 0–2B | [SAM3 and depth limitations](https://github.com/chao142857/astra-realman/blob/c7597fc27c8744044741888a9e6fff6e60a891cf/aspire_realman_phase1b/README.md) · [Phase 2B GPU/Stub and blockers](https://github.com/chao142857/astra-realman/blob/c7597fc27c8744044741888a9e6fff6e60a891cf/aspire_realman_phase2a/PHASE2B.md) |

## Reproducibility and safety

- **Select a specific snapshot first.** Branches represent distinct experiments; newer dates do not imply a stronger model, a fully merged codebase, or a superseding real-robot result.
- **Follow the corresponding experiment report.** A run may involve an external model, a physics engine, a scripted baseline, a heuristic Stub, or a synthetic base. Preserve that distinction when reporting results.
- **Git is not the entire evidence archive.** Full videos, RGB-D recordings, traces, calibrated assets, models, and some manifests remain on experiment workstations. The V17 report describes an external archive and checksum; the files are not claimed to be publicly downloadable from this repository.
- **Hardware execution is not authorized by documentation.** Simulator defaults and historical test scripts must not be assumed safe on physical arms. Verify the actual robot, frames, TCP, calibration, collision coverage, supervision, and stop mechanism before any independently authorized physical experiment.

## What this project leaves behind

The main outcome is a set of concrete research artifacts: a real-robot execution and observation harness, a documented one-off dual-arm success, spatial-input and contact counterexamples, and an incomplete but measurable ASPIRE integration. The unresolved problems—especially reliable world grounding, geometry completeness, hardware calibration, reproducibility, and robust closed-loop manipulation—are recorded rather than hidden behind a demo.

**Maintainer / integration and experiments:** [@chao142857](https://github.com/chao142857)  
**Snapshot period:** October 5–21, 2026  
**Archive review:** October 22, 2026
