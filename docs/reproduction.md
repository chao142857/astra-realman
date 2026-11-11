# Reproduction and dependencies

Choose the experiment branch before running commands; `main` retains the original harness baseline, not a union of the other implementations. [Source and evidence index](experiments.md).

## Ordinary-computer checks

The commands below were run on macOS on November 12, 2026. They use offline fixtures, mocked execution or replay; none reproduces the physical V17 run. Run from the corresponding branch root with a suitable `python3` (Python 3.12 was used for the dependency-bearing checks). No installation or download is required if those dependencies already exist.

| Branch | Checked scope | Result |
| --- | --- | --- |
| `main` | API2 state conversion and mocked SDK lifecycle | 14 tests passed |
| `realman/v17` | Mocked dual-arm coordination and failure handling | 18 tests passed |
| `research/spatial` | Core spatial evaluation, `test_eval.py` | 24 tests passed |
| `research/rm65` | Action-chunk contract and sequential scheduling, with `jsonschema` | 8 tests passed |
| `develop/aspire` | Phase 0 replay/contract tests | 19 passed; 8 native-ASPIRE tests skipped without pinned upstream source |

```bash
# main — selected classes avoid the external legacy-driver comparison
mkdir -p astra_realman_harness/logs
PYTHONPATH=astra_realman_harness/tests python3 -B -m unittest \
  test_api2_readonly.CanonicalTests test_api2_readonly.LifecycleTests

# realman/v17
python3 -B -m unittest discover -s astra_realman_harness/tests -p test_parallel_arms.py

# research/spatial
PYTHONPATH=experiments/spatial_input_eval_v0 python3 -B -m unittest discover \
  -s experiments/spatial_input_eval_v0/tests -p test_eval.py

# research/rm65 — requires jsonschema
PYTHONPATH=experiments/rm65_handoff_v1 python3 -B -m unittest discover \
  -s experiments/rm65_handoff_v1 -p chunk_protocol_tests.py

# develop/aspire — dependency-free replay checks; native tests may skip
python3 -B aspire_realman_phase0/tools/run_offline_tests.py
```

**Known local limitations.** The full baseline `test_state_semantics.py` cannot import the absent `transforms` module. The full API2 test file also needs the laboratory's external legacy RealMan driver for one comparison. The 143-test spatial suite was attempted with existing NumPy/Pillow/jsonschema and loopback mock access: 140 passed, two errors required missing SciPy, and one connection-refusal classification assertion failed. These are retained limitations, not a fully passing suite. An additional syntax scan found one already-invalid Python file inside an RM65 historical `evidence/.../source_snapshot/` copy (`summarize_right_grip_repair.py`, line 34); the current implementation parsed successfully. No source code or historical snapshot was changed to conceal these limitations.

## Simulation and external assets

- **Spatial:** [package and CLI](https://github.com/chao142857/astra-realman/tree/research/spatial/experiments/spatial_input_eval_v0) requires Python ≥3.10. Full geometry/image tests additionally use NumPy, Pillow and SciPy. [Lab reproduction](https://github.com/chao142857/astra-realman/blob/research/spatial/experiments/spatial_input_eval_v0/lab/README.md) and [B-v2 reproduction](https://github.com/chao142857/astra-realman/blob/research/spatial/experiments/spatial_input_eval_v0/lab/b_v2/README.md) distinguish stored inputs, mock evaluation, rendering and real model calls. SAPIEN scene rendering requires its compatible GPU/runtime and assets.
- **RM65:** [simulation guide](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/README.md), [isolated dependency versions](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v0/requirements-isolated.txt), and [D4/contact report](https://github.com/chao142857/astra-realman/blob/research/rm65/experiments/rm65_handoff_v1/INTERFACE_REPAIR_YANGLAB_20261017.md). Historical runtime used Python 3.10, SAPIEN 3.0.0b1, mplib 0.2.1, NumPy 1.26.4 and SciPy 1.10.1 plus robot meshes and simulator assets. Asset paths are workstation-specific; no clean-machine physics replay was performed here.
- **Persistent World:** [comparison entry and dependency context](https://github.com/chao142857/astra-realman/blob/realman/v17/LAB_CODEX_HANDOFF_1011.md) uses SAPIEN, RGB-D assets and model transport. Ordinary and occluded comparison scripts are simulation entries, not physical-robot launchers.
- **ASPIRE:** [native CPU setup and exact upstream revision](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase05/NATIVE_INTEGRATION.md) and [dependency lock](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase05/requirements.lock). Native ASPIRE targets Python ≥3.10,<3.13. [SAM3 checks](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase1b/SAM3_REAL.md) additionally require official weights, the sealed input and GPU environment. [Phase 2B](https://github.com/chao142857/astra-realman/blob/develop/aspire/aspire_realman_phase2a/PHASE2B.md) requires pinned cuRobo/CUDA, robot assets and the native adapter. These GPU and laboratory dependencies were not rerun for the documentation update.

## Real RealMan hardware

The V17 source entry is [`astra_realman_harness/launch/hardware_gui.sh`](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/launch/hardware_gui.sh). It is a laboratory launcher, not an offline smoke test. Physical reproduction requires the corresponding dual-arm setup, SDK and gripper driver, calibrated frames/TCP/cameras, external model access and supervised execution environment described in the [V17 record](https://github.com/chao142857/astra-realman/blob/realman/v17/astra_realman_harness/docs/V17_SUCCESS_SNAPSHOT_20261018.md).

Full raw archives, model inputs, credentials, private calibration assets and unapproved laboratory media are not supplied by these instructions. Historical workstation paths identify evidence locations; they are not portable setup commands. This documentation update started no hardware, cameras or model episodes.
