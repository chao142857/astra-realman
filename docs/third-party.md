# Third-party sources and licensing

No standard repository-level LICENSE was found on any of the five branch tips inspected on November 12, 2026. This documentation update does not add a blanket license: the integration code's licensing decision remains with its author, and external code, models, SDKs and assets retain their own terms.

| Component | Source / notice inspected | Scope |
| --- | --- | --- |
| RoboTwin scene support | [Preserved MIT notice](https://github.com/chao142857/astra-realman/blob/research/spatial/experiments/spatial_input_eval_v0/lab/ROBOTWIN_LICENSE) | Applies to the covered upstream material, not the entire Astra repository |
| ASPIRE | [LICENSE at pinned `fa00f0e`](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/LICENSE), [NOTICE](https://github.com/NVlabs/ASPIRE/blob/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7/NOTICE) | Apache-2.0; NOTICE explicitly says third-party submodules have their own licenses |
| cuRobo | Cached upstream LICENSE: Apache-2.0; [upstream](https://github.com/NVlabs/curobo) | External planner; experimental revision is recorded in the [Phase 2B report](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase2a/PHASE2B.md) |
| SAM3 | Cached official `SAM3-official` source at `7f473cfd983d5eb43040ff608f66bff0d7bdcb53`: [SAM License](https://github.com/facebookresearch/sam3/blob/7f473cfd983d5eb43040ff608f66bff0d7bdcb53/LICENSE) | Separate terms for SAM materials; do not relabel as Apache/MIT or redistribute weights by implication |
| RealMan SDK, robot/mesh/calibration assets | External installation referenced by the experiment records | No complete redistribution-rights audit or bundled SDK license was established; no SDK or private assets were added |
| Astra / decision backend | External model access and local transport adapters | This repository records integration and experiments, not ownership of the model |

[Platform media provenance](../assets/README.md) records the already-public owner-supplied demo. Its reuse here does not license private experiment recordings or raw data. Existing third-party notices and historical evidence were preserved.
