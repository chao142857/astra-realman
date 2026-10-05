# Astra → RealMan shadow harness

Current entry point: `scripts/run_decision_shadow.py`.
All new code/configuration/tests/logs stay under
`/home/tongji/alex/astra_realman_harness`.
There is no physical motion executor, homing, gripper actuation, error-clear or frame-set path.

## Current data flow

Four real RGB images + both arms' API2 read-only canonical states
→ DecisionBackend (CodexBackend or unavailable AstraBackend)
→ strict ActionProposal parser
→ independent frame/safety gates
→ DryRunExecutor log.

Only the physical left arm at 192.168.1.19 may receive a proposal.
Evidence: user confirmation “19左，用19”, plus existing laboratory configuration references
in `config/shadow_phase1.json`. Software right maps to .18; its physical side is unconfirmed.
Both controllers are queried for state/error diagnostics. Any nonzero/unknown controller error rejects,
including a NOOP. SDK handle IDs are process-local connection handles, not hardware serial numbers.

## ActionProposal v2

Exactly these eight fields; no extra keys, Markdown repair or natural-language conversion:

```json
{
  "action_type": "cartesian_delta",
  "arm": "left",
  "frame": "realman:left:work:World",
  "tool_frame": "realman:left:tool:Arm_Tip",
  "translation_m": [0, 0, 0],
  "rotation_rpy_rad": [0, 0, 0],
  "gripper": "hold",
  "done": false
}
```

Use the actual observed work/tool IDs, not these example names if the active frames change.
Translation is metres along explicitly named work axes, each component <= 0.002 in absolute value.
Rotation must be exactly zero; gripper must be hold. `done` never bypasses safety.
All backends use `schema/decision_action.schema.json`.
Older seven-field proposals are rejected rather than having an implicit tool inserted.

## Frames and units

The pinned API2 SDK is loaded from
`/home/tongji/aloha/RealMan_Control/Robotic_Arm/rm_robot_interface.py`;
the actual `libs/linux_x86/libapi_c.so` path is checked.
API2 values already have joint deg, xyz m and RPY rad units. No /1000 or /1e6 is applied.
RPY metadata specifies ZYX intrinsic, with R = Rz(yaw) Ry(pitch) Rx(roll).

Canonical states preserve all raw SDK state/frame returns, identity-converted values,
units, active frame IDs, definition fingerprints, IP/handle provenance, errors and timestamps.
Work/tool reads bracket each state query. A stable bracket is not an atomic controller snapshot.
The SDK call allowlist is only rm_init, rm_create_robot_arm, rm_get_current_arm_state,
rm_get_current_work_frame, rm_get_current_tool_frame, rm_delete_robot_arm, rm_destroy.

Local documentation establishes work relative to controller base and tool relative to flange.
It does not explicitly establish the reference/target of the current-state EE pose.
EE reference_frame_id/target_frame_id therefore remain null, with UNKNOWN binding.
Active names, zero frame offsets and static numeric agreement do not resolve that ambiguity.
No grasp TCP or shared lab-world frame is invented.
Evidence is in `docs/api2_frame_evidence.json` and `docs/phase1_evidence.json`.

The adapter uses an already explicit robot-work-frame delta; it performs no camera-to-robot
geometric transform. Missing camera extrinsics are a perception/grounding warning.
A future adapter that actually depends on such a transform must reject missing calibration.
A numeric target-position preview is produced only when EE frame binding is confirmed.

## Safety outcomes

- PASS_NOOP: schema-valid exact zero translation, zero rotation, hold. No actuation is generated.
  Controller health, unit validity, explicit active IDs, four-image integrity and camera timing
  still must pass. State freshness and movement-specific conditions are recorded but not required
  for doing nothing; their unknown/failing observed status remains in every gate's log.
- PASS_EXECUTABLE: nonzero proposal and every execution condition verified, including fresh state,
  matching frame/tool definitions, physical identity, certified workspace/clearance, trajectory
  validation, operator authorization and a hardware executor. Actual shadow runtime supplies no
  authorization or hardware executor, so real nonzero proposals cannot receive this outcome now.
- REJECT: malformed proposal, failed common gates, or nonzero action lacking any execution condition.

Even PASS_EXECUTABLE is only a classification: DryRunExecutor always records
execution_permitted=false and hardware_commands_sent=motion_commands_sent=0.
Offline synthetic fixtures exercise this branch; they cannot be used as real observations.

A local workspace is not yet certified: bounds remain null. The user offered manual teaching.
A demonstrated path alone does not certify a surrounding collision-free volume. Any later region
must bind to exact work/tool IDs and fingerprints, record human evidence and certify the tool's
swept clearance. The 2 mm step bound is not a workspace radius.
Full gripper geometry remains unconfirmed. A certified local free-space translation may carry
that warning, but approach/descent/closure require geometry verification.

Nonzero observation/state/proposal age limits remain 30 seconds; clock skew <= 1 second;
camera span <= 1000 ms. Inference never refreshes observation timestamps or increases limits.
Every gate is logged even if another gate has already failed. Common malformed inputs fail closed.

## Persistent cameras and decision isolation

CameraSession waits for the expected serials using bounded read-only enumeration in one context,
records each discovery attempt, then opens four pipelines once, continuously reads one producer per camera,
and snapshots their latest buffers together. Repeated observations can reuse one session.
Each image has its own timestamp, source domain, frame number, serial and SHA-256.
capture_span_ms is independently recomputed from those timestamps. Unknown timestamp domains
and excessive span reject. No advanced-device configuration, reset, exposure or hardware sync is set.

Codex uses the existing remote API-key login and configured https://xmapi.site/v1 route;
no ChatGPT login or new key is required. The model ID is explicit, with no fallback.
AstraBackend remains a placeholder. CLI uses four --image attachments, --output-schema,
--sandbox read-only, --ephemeral, --ignore-user-config and approval_policy=never.
Shell/code executors, agents, user MCPs, apps/plugins/hooks and browser/computer tools are disabled.
Images and observation data cannot authorize tools or hardware.
Only the exact previously verified nonfatal startup notices are allowed. Other errors,
tool events, timeout, missing or invalid output reject. Timeout affects only that owned CLI child.
CLI arguments, prompt, raw final output, event stream, image hashes and latency are logged.
Runtime paths remain inside the run directory; secrets are not copied into configuration/logs.

The prompt requests a minimal correction toward the tennis-ball task only when safe robot-axis
direction is justified by the views and verified evidence; otherwise zero translation.
A NOOP does not establish object detection or a successful grasp.

## Commands

On the workstation terminal:

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B \
  /home/tongji/alex/astra_realman_harness/scripts/run_decision_shadow.py \
  --backend codex --model gpt-6-astra \
  --task "左臂抓取网球 shadow 验证；方向或局部净空不可靠则 NOOP，否则只提议最小 Cartesian correction，每轴不超过 2 mm，rotation=0，gripper=hold。禁止执行。"
```

From the Mac, wrap the command with `ssh yanglab '...'`; do not SSH to the alias from
the workstation itself unless it also has that alias configured.
Exit 0 means PASS_NOOP or PASS_EXECUTABLE classification; exit 2 means REJECT.
Neither exit code means a hardware command was sent.

Offline tests, without camera/SDK/network/model invocation:

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B -m unittest discover -s /home/tongji/alex/astra_realman_harness/tests -v
```

Saved current-version results can be revalidated with `scripts/replay_codex_decision.py --source-run <run>`.
Replay never calls a model or hardware and never updates source timestamps.
Older action/policy versions are not silently migrated.

## Preserved legacy paths

`demo_real_dryrun.py`, `harness.py`, `protocol.py`, `safety.py` and `config/lab.json`
retain the earlier fixture/raw-socket diagnostic behavior. They are separate from the current
decision shadow path and its `config/shadow_phase1.json`.
Raw socket integers require /1000 joint/RPY and /1e6 xyz conversion only on that legacy transport.
Never apply those scales to API2 output.

`verify_api2_readonly.py` and `legacy_state_compare.py` remain read-only SDK compatibility
diagnostics. No physical single-step execution command exists.
Previous reports and before-edit source backups remain under logs.
