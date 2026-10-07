# Exact-target IK fallback

Implemented in `exact_target_feasibility.py`; shared by the existing left/right
workers and ArmStack. No action, context, parser, executor or runtime loop changes.

1. Existing single-solution IK, with recorded joint seed, exact pose, flag=1.
2. Only return 1 triggers traversal-mode single-solution IK with fresh buffers
   containing identical inputs. Restore SDK process-global traversal mode to False
   in finally. Calls are serialized within a process; parallel workers already
   have separate SDK processes.
3. If still unsolved, require successful `rm_get_robot_info` confirming RM_65 and
   six DOF. Call `rm_algo_inverse_kinematics_all`. Record result, num, q_ref and
   every returned candidate row. Check the first six joint values of each candidate
   using the official joint-position-limit function. Select the valid candidate
   with smallest squared distance (degrees) to the original seed. No angle wrapping.

Only exhaustion of these stages yields REJECTED_IK. Missing APIs, unexpected
returns, invalid candidates, failed model identification or failed limit checks
are CHECK_ERROR. No pose scaling, projection, clamping or neighbor search occurs.

The selected joints are evidence for preflight only. The unchanged executor still
calls rm_movej_p with the original target; this does not force its controller to
use the selected IK branch. Endpoint IK does not certify collision-free paths.

## Solve-only replay

On the lab workstation, from the isolated checkout containing this revision:

```bash
/home/tongji/miniconda3/envs/dp/bin/python -I -B astra_realman_harness/scripts/replay_exact_ik.py --logs-root /home/tongji/alex/astra_parallel_arms_20261007/astra_realman_harness/logs
```

Alternatively pass `--record /absolute/path/to/check.json`; group_preflight.json
also requires `--arm left` or `--arm right`. With --logs-root, select the latest
REJECTED_IK record by modification time; --arm optionally filters the arm.
The replay connects for SDK lifecycle, model/frame reads and pure algorithm calls,
never imports an executor or invokes motion/gripper functions. It uses the archived
seed/target/flag, never substitutes current joints or recomputes the target.
It runs all three solvers, even if the first now succeeds. Current frame names
must match. Historical frame definitions may be unavailable: that comparison is
explicitly UNKNOWN, so replay is solver diagnostics, not an execution permit.
Results go to this checkout's `astra_realman_harness/logs/ik-replay-*/result.json`.

Local SDK source verified:
`/home/tongji/aloha/RealMan_Control/Robotic_Arm/rm_robot_interface.py` and
`rm_ctypes_wrap.py`. This version's joint-limit wrapper needs a ctypes float[6]
argument despite its list type annotation. No new SDK/version is installed.

Do not replace code in a running experiment. Use this isolated revision for the
next process. No robot motion or live fallback call was performed during development.
