# Lab handoff 2026-10-11

Branch: `1011`. Based on `7e00082e744064ee4a5b9a7a40ed2a955feac963`; includes subsequent actual simulation runtime increments through the cached A/B batch.

## Entry points

- Normal A/B: `scripts/run_persistent_chunk_pair_episode.py`
- Occlusion A/B: `scripts/run_occluded_chunk_pair_episode.py`
- Shared occlusion event: `scripts/transport_occlusion_event.py`, `config/research/ab_occlusion_panel.json`

Run from `astra_realman_harness` with the existing SAPIEN/mplib environment and `PYTHONPATH=.`. Each runner takes `--out`, reads that directory's protocol and authorization, and creates exclusive claims. Existing consumed authorizations must never be reused. Provider launcher, sealed inputs and raw episode archives remain external; this source checkout alone does not authorize any new model or physics run. No credentials or raw RGB-D/video archives are included.

The normal and occlusion entry points are exact copies of their respective frozen runtime scripts. The shared source comes from the latest occlusion snapshot. Included manifests refer to those original runtime snapshots, not this Git tree.

## Evidence location and current status

Original evidence: `/home/alex/astra-realman_ws/ab-cached-scenes-20261011`. Preserve all raw files and scores.

- NORMAL_A_FULL_SYSTEM: FAIL_STOP / PNP_FINE_CONTRACT, policy K=9; 284.786s.
- NORMAL_B_VANILLA_ASTRA: PASS / MODEL_FINISHED, policy K=11; 276.283s.
- OCCLUDED_A_FULL_SYSTEM: FAIL_STOP / INFER_FAILED_NO_RETRY, policy K=7; 225.363s.
- OCCLUDED_B_VANILLA_ASTRA: pending at handoff; no result asserted.

These are individual runs, not statistical superiority evidence. Local contract/service errors must be distinguished from physical capability. Engineering initialization is counted separately. `physical_success` and `model_finished` remain independent.

Ancestor proof caching is explicitly enabled by the runner; current-root evidence is still validated, guarded ancestor reuse and full recursive audit remain available. Cold proof cost is counted within the full wall clock, not added twice. Runtime records: `RUNTIME_CACHE_AUDIT.json`, `RUNTIME_CACHE_FINAL.json`, `HOST_TIMING.jsonl`.

Hardware remains prohibited without separate authorization. No safety thresholds were changed for this handoff.
