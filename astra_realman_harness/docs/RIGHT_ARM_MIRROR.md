# RIGHT = existing LEFT stack mirror

Mac development branch: `codex/right-arm-mirror-20261007`, based on foundation `5c24866791106711a1945c60435a4d27e639bef6`. Foundation branch remains at that commit. No push or credential change on laboratory workstation.

## What changed

- `left_executor.py`: `RealArmExecutor(..., arm_id=...)` routes the same `rm_movej_p(pose, 1, 0, 0, 1)`, per-channel exclusive dispatch claim, SDK result, intermediate readback and no-retry logic. Legacy `RealLeftExecutor` preserves left-only session checks; `RealRightExecutor` is the right wrapper.
- `exact_target_feasibility.py`: state/seed/frame/session handle now follow `action.arm`. Same `rm_algo_inverse_kinematics(... flag=1)`, exact target, no projection or retry. Shared sessions are explicit; legacy calls keep their single-arm default.
- `lab_gripper_adapter.py`: `LabGripperAdapter(arm_id, config_path=None)` chooses existing rm_left/right_arm.yaml and checks the corresponding IP/8080. It still invokes unchanged `RmArm.set_gripper_position`, observes its existing hand_follow_pos bytes, sends once, and retains raw feedback. Normalized opening 0=closed, 1=open; not force.
- `left_terminal.py`: parser and state validator accept arm/frame arguments; old defaults are unchanged. No old GUI or loop entry is redirected.
- `arm_stack.py`: common read/pose/delta/gripper/action facade, two-arm SDK capture and symmetric robot_states/work_frames/tool_frames model projection. SDK unit normalization is unchanged. Raw telemetry stays in logs.
- `scripts/run_arm.py`: independent one-action terminal entry, default read/preflight, explicit --execute for hardware.
- `bimanual_demo/executors.py`: former real-executor placeholder delegates to ArmStack. `make_arms(..., mode='real', session=..., capture=..., stop=..., root=...)` selects the real adapters when explicitly enabled. The existing synthetic episode remains synthetic; it does not run synthetic waypoint numbers on hardware. Real sessions and observation capture must be supplied by the caller. No shared-frame transform or new planner was added.
- `config/arm_mirror.json`: known endpoint/config mappings and unchanged four serials; fourth remains additional_view with candidate_role=right_wrist until actual mounting confirmation.

Raw proposals, parsed action, planned command, IK result, actual dispatched command, SDK result, and after state are separate files. Command/controller/readback failures stop; IK rejection sends neither arm nor gripper. No tracking-residual stop was introduced.

## Laboratory commands

After deploying this branch into the independent directory:

```bash
cd /home/tongji/alex/astra_right_mirror_20261007/astra_realman_harness
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/run_arm.py --arm right --both read
```

This is read-only: current SDK state, frames, errors and gripper feedback for both arms. It does not instantiate the gripper command driver, query the model or capture cameras.

Same CLI for left: change only `--arm right` to `--arm left`. Pose/delta commands use that arm's current controller-returned work/tool IDs.

```bash
# Preflight only; no actuator command
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/run_arm.py --arm right delta --xyz 0 0 0.001

# Explicitly initiated one-action hardware commands; do not run as a batch
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/run_arm.py --arm right --execute delta --xyz 0 0 0.001
/home/tongji/miniconda3/envs/dp/bin/python -I -B scripts/run_arm.py --arm right --execute gripper --opening 0.5
```

`pose --target X Y Z RX RY RZ` accepts one absolute controller-frame pose in m/rad. `action --json PATH` accepts the existing eight-field Cartesian action; arm/frame/tool_frame must all agree. `--execute` is a global option before the subcommand. No automatic retry, recovery, task loop or return-to-home.

For existing Astra-compatible JSON (shown as format, not a saved command):

```json
{"action_type":"cartesian_delta","arm":"right","frame":"realman:right:work:World","tool_frame":"realman:right:tool:Arm_Tip","translation_m":[0,0,0.001],"rotation_rpy_rad":[0,0,0],"gripper_opening":1,"done":false}
```

Use the names returned by `read`; the implementation does not invent right World/Arm_Tip if the controller uses different names. `model_input` generates the corresponding enums. Pose is translated to the same component-wise delta/target semantics; no transform to left World.

Optional `--cameras config/arm_mirror.json` reuses CameraSession, captures the existing four views and includes both state dictionaries with `--both`. Raw/current image metadata is preserved. A state-only read has no images and does not call Astra.

Logs: `logs/arm-right-<time>-<id>/`, with SDK reads, raw gripper current/other returned fields, model_input.json, and per-operation subdirectories under operations/. Each operation identifier is consumed once; existing journal directories cannot be reused after restarting the facade. Ctrl-C prevents subsequent command dispatch, but is not a claim of an SDK emergency-stop command.

## Known inputs / one unresolved physical role

Verified by read-only file inspection: left `.19:8080`, right `.18:8080`, right config `arm_axis: 6`. The lab's current left executor, gripper adapter, and exact-target checker hashes matched their Mac source before parameterization. Neither controller nor gripper was contacted for this change.

No new robot geometry/calibration parameter is required for the single-arm mirror. Current right work/tool names, definitions, error and feedback are obtained by the first read command. These are not yet a new physical execution test.

`348522072063` is historical `cam_right` in `config/lab.json`; its current physical mounting is not verified by repository text. After the operator confirms it is on the right wrist, set that entry's `role` to `right_wrist` and `role_confirmed` to true in `config/arm_mirror.json`. Do not use the historical label as new installation evidence.

URDF inventory: bounded read-only search under `/home/tongji/aloha` and `/home/tongji/DP` found DP block-pushing/suction assets, not a RealMan model used by this chain. Static inspection of the actual state→exact-IK→rm_movej_p/gripper path shows no URDF consumption. No URDF dependency added; this does not claim none exists elsewhere on the workstation.

## Offline verification

24 new mirror tests: both handle routes, exact target, right gripper config/wire, no retry, IK rejection/fault separation, error stopping, frame changes between channels, post-gripper health, raw/parsed/executed logs, symmetric model fields, and foundation real-adapter routing with mocks.

Regression suites: left executor 11; exact-target checker/three- and four-camera mocked loops 11; history diagnostics 10; simulation/gripper scale 6; bimanual foundation 37. Total **99 passing tests**. No real model/hardware calls. Legacy loop tests used copied archival observation/images with only local path relocation; those ignored artifacts are not committed.
