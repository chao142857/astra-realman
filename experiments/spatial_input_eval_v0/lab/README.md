# Yanglab pure simulation acceptance, 2026-10-13

Base commit `1925370`, branch `codex/spatial-eval-lab-20261013`. Workstation checkout: `/home/tongji/alex/spatial-eval-lab-20261013`. Existing dirty laboratory checkouts, RealMan programs, controllers, SDKs and logs were preserved. No robot, physical camera, ROS, IK or gripper interface was connected or imported by the new simulation code. No Astra generation request was made.

## Actual acceptance

`../evidence/lab_20261013/delivery.json` is the machine-readable delivery record. Original 31 tests and final 33 tests passed on yanglab. The archived S1 snapshot produced four valid mock records/two A/C pairs. The new six scenes produced 24 valid mock records/12 pairs. Mock scores are plumbing checks, **not model capability evidence**. The one-command script ran successfully and its outputs remain under `script_acceptance/`.

| New scene | Geometric coverage | Acceptance |
|---|---|---|
| lab_s1_relations | Multiple views, x/y/z relations, position, size, top height, projected gap | Calibrated pixels correspond to measured boxes |
| lab_s2_occlusion | Front-view occlusion and depth ordering, other-view visibility | Front target visibility <35% of side; overhead target visible |
| lab_s3_narrow_container | Box dimensions exceed container interior | Identity fit fails; separate feasible placement task |
| lab_s4_rotated_fit | Long cuboid, rotated container fit | Identity fit fails, 90-degree fit and placement pass |
| lab_s5_placement | Occupied target volume | A collision-free off-center placement passes; illegal placement fails |
| lab_s6_held_object_detour | Fixed-orientation held-box obstacle avoidance | Private detour witness passes; direct shortcut fails continuous collision check |

The simulation uses **actual SAPIEN 3.0.0b1 GPU rendering and PhysX**. It reuses the exact `Base_Task.setup_scene` method from the laboratory's archived RoboTwin commit `6dde57155eafa3e4ebf6ad1f93a7cf7d5d41a755`, with upstream source and excerpt hashes in `upstream.json` and the MIT license retained. Only scene initialization is imported. Running a complete RoboTwin task would additionally load robot/planner dependencies; those are unnecessary for this static spatial benchmark and were not installed. The archive contained source/assets/history, but none of the inspected active Python environments had SAPIEN before this recovery.

The archived unsupported OIDN denoiser is disabled. Cameras use the default raster shader for deterministic RGB and calibrated depth/segmentation G-buffers. These settings are recorded, and are distinct from the archived RT shader. Static collision boxes hold their poses while physics advances ten steps at 250 Hz. All three views capture the same immutable step; `capture_span_s` is measured sequential readback time, not a claim of simultaneous wall-clock acquisition. Every view is 640×480. Depth is lossless float32 optical z in meters, invalid pixels are zero with a separate boolean validity mask. Extrinsics explicitly distinguish SAPIEN pose, OpenGL and OpenCV conventions.

`sim_suite_initial/` is the primary frozen dataset; `sim_suite_repeat/` is its independent rerender. All 72 RGB/depth/validity/segmentation assets are byte-identical, and tasks, calibration and geometry match. Measured wall-clock fields differ. `acceptance_final/` validates real image decoding, depth SHA/binding, calibration reprojection, visible pixels against measured box surfaces, planning witnesses, negative controls, all provider schemas/payloads, A/C parity, GT canaries and actual A/C input-only bwrap isolation. The prepared RGB-only A request also passed native CLI `debug prompt-input`, with exactly three readable images and an unchanged prompt. All diagnostics have zero generation requests.

## Start on yanglab

Already installed and tested: Ubuntu 20.04.6, RTX 3060 12 GB, driver 535.230.02, Python 3.10.19, isolated SAPIEN environment, standalone official Linux Codex CLI 0.160.0. System Python 3.8 and Node 10 were not changed. The standalone native CLI runs without the Node launcher; its version/help passed inside the production bwrap. The bridge still checks the visible Node version in its preflight.

```bash
ssh yanglab
cd /home/tongji/alex/spatial-eval-lab-20261013
bash experiments/spatial_input_eval_v0/lab/run_offline.sh /tmp/spatial-eval-NEW
```

The output directory must not exist. The script runs tests, reads bundled S1, renders six real scenes, verifies them, builds A/C requests, runs mock/independent scoring, rerenders and verifies reproduction. It contains no inference flag, hardware entry point or authentication operation. Keep a new output directory for each run.

To reuse the already frozen data without rendering:

```bash
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
.venv/bin/python -m spatial_eval.cli run \
  --snapshot experiments/spatial_input_eval_v0/evidence/lab_20261013/sim_suite_initial/*/snapshot.json \
  --output /tmp/spatial-mock-NEW
```

For a new Linux x86_64 checkout with Python 3.10, `bash experiments/spatial_input_eval_v0/lab/bootstrap_lab.sh /absolute/python3.10` creates a fresh isolated environment using `requirements.lock.txt` and the hash-pinned official CLI package. It refuses existing runtimes, changes no authentication and sends no generation request. The individual installation commands and dependency lock were tested; this combined fresh-bootstrap wrapper has shell syntax validation only, since the installed runtime is preserved.

Non-generation native preflight and account metadata, using existing authentication in place:

```bash
export SPATIAL_EVAL_ENV_CONFIG="$PWD/experiments/spatial_input_eval_v0/lab/environment.yanglab.json"
# For a different checkout use the bootstrap-generated .toolchain/environment.json.
.venv/bin/python -m spatial_eval.cli preflight --output /tmp/spatial-preflight-NEW
.venv/bin/python experiments/spatial_input_eval_v0/diagnostics/run_metadata_probe.py \
  --kind account-routing --output /tmp/spatial-account-NEW
```

The optional environment configuration allows only `cli_executable`; it cannot change model/provider/reasoning settings. A narrowly scoped read-only mount for the venv's Python base runtime fixes Conda interpreter symlink resolution. No simulator, GT, evaluator, home directory or controller workspace is added to model mounts. Production harness files are unchanged. The OpenAI configuration guidance is at [Config basics](https://learn.chatgpt.com/docs/config-file/config-basic); exact flag acceptance was verified against the installed binary.

## Data boundary and limitations

Each scene contains `assets/` with actual rendered RGB-D and segmentation; `snapshot.json` for the independent evaluator; `private/` with simulator truth, camera matrices and a geometric planning witness; and `model_inputs/<task>/<condition>/` with **only** allowlisted context, three identical RGB files and a manifest. Ground truth and the private witness are never model attachments. Do not expose the entire dataset as a model workspace. Oracle objects/obstacles are read back from actual PhysX box collision shapes and actor/shape poses, rather than fabricated image annotations. Regions are public task definitions; container wall/floor solids are independently exported. No reference placement, trajectory, answer, score, old action history or depth pixels are in the model package.

The simulation world equals the `robot_base` evaluation frame. There is no robot state: joints are empty and flange pose is null in all conditions. Ground is a simulation plane at z=0; every legal target/workspace volume stays above it, and plane contact/support is outside this box-only geometric benchmark. Gray table/container/barrier boxes are measured GT obstacles. Green region edges are declared visual-only annotations and not obstacles. Understanding uses the fixed V0 question schema; orientation is tested indirectly through prescribed-orientation fit, not a new direct quaternion-estimation output.

The scorer tests static OBB containment and continuous translation at fixed orientation. It makes no support/stability, hand/gripper, robot reachability, dynamics or IK claim. Oracle and evaluation geometry share simulator provenance but are serialized through separate boundaries; evaluator witnesses are additionally private. B remains unavailable until actual reconstruction is provided. No training or reconstruction network was installed. Box primitives are real simulator geometry, not illustrative fixture PNGs.

## Real Astra readiness and remaining blocker

417 archived laboratory records contain strict nonempty Astra JSON and a completion event, using `CodexAstraBackend`, OpenAI provider and **Mac ChatGPT login** through the SSH bridge. They use older action schemas and may include duplicate archived logs; the distinct event-hash count is in `delivery.json`. They establish historical model-interface success, not spatial benchmark accuracy or current native availability. No historical hardware action was rerun.

The newly prepared native Linux CLI uses existing **API-key** authentication. Its metadata response is `ACCOUNT_READ_RESPONSE`, account type `apiKey`, `workspaceRouting=null`. This is not the historical ChatGPT route. The non-bundled catalog equals the bundled catalog, so it supplies no evidence of remote discovery or Astra entitlement. The bundled Astra entry says `tool_mode=code_mode_only`; the original bridge disables `code_mode_host`. Local parsing/input/preflight pass, but generation compatibility is unproven. The warning alone does not establish a failure cause, and tool/model settings were not changed.

Before any real request, resolve the intended authenticated interface using existing credentials in place and non-generation account/input checks. Do not copy credentials, alter the original successful bridge, or assume the personal Ubuntu network failure applies here. **A new explicit user authorization is still required.** No real A/C comparison is delivered.

If one request is authorized later, retain the same frozen A input, `gpt-6-astra`, medium effort and existing 90-second qualification profile. Record sanitized request-send time, HTTP/WebSocket status, stream event timestamps, completion and available usage, excluding credentials. No outbound request indicates client/runtime trouble; outbound send with no response narrows the issue to transport/server waiting; an explicit configuration rejection identifies incompatibility. Without those observations retain an unresolved diagnosis. Do not retry, raise timeout, substitute a model or run C until a real valid A JSON is obtained.

Raw diagnostics, failed initial dependency-resolution attempt, successful pinned installation, initial/final validations, rerenders and the tested wrapper run are all retained. Login-status key fragments were redacted before committing. `.venv`, `.toolchain`, binary distribution and credentials are excluded from Git; dependency and package hashes provide reproduction instead.
