# Fixed-scene scheduling and cost small-batch check

Frozen runtime base: `1b5e1842e90887d347819daefa422cbabea29c21`.
This follow-up only adds `scripts/run_sim_ms_pilot.py`, its offline boundary
tests, and this documentation. Existing policy/physics code, prompt, targets,
CLI configuration and dependencies are unchanged.

The one authorized batch consists of exactly these new episodes in this order:

| Seed | Condition | Maximum top-level model calls |
|---|---|---:|
| 2 | M | 4 |
| 2 | S | 1 |
| 3 | S | 1 |
| 3 | M | 4 |

The wrapper requires `--authorize-model --max-model-requests 10`, creates a
previously nonexistent batch directory, and invokes the existing
`run_sim_placement.py` in a fresh process for each episode. Video remains off
for all four episodes, matching the channel validation. Each placement uses the
existing total 120-second budget; LocalPolicy passes at most the remaining time
to infer. Physics stays paused during decisions. No prompt/model call is made by
the batch wrapper itself. No unused calls are reassigned or retried.

All four rows are declared before execution. Valid policy stop and terminal
independent-score FAIL are retained and permit the next scheduled episode.
Interface, protocol, initialization, common-check or execution errors end the
batch, leaving remaining rows NOT_RUN. Unknown or incomplete records also stop
the batch. Failed attempts count; a conservative per-episode cap reservation
cannot exceed ten even if a child fails before writing its final result.

Reports preserve each request's raw/parsed/command/latency/usage and each
episode's full result and starting observation. Usage is aggregated only across
identical numeric field names, never by adding cached/reasoning subcounts to
input/output. Missing usage remains marked incomplete; raw dictionaries are
retained. The original success and failure channel records are excluded.

Initialization wall time is derived from existing monotonic phase timestamps:
scene INITIALIZING to the first placement OBSERVE_ENTER. This includes scene
construction and scripted held-object setup, excluding preflight/imports.
The unchanged placement summary supplies placement wall/physics time. Separate
nonplacement wall time includes peripheral overhead and cleanup and is not
labelled pure initialization. Starting private object data is only copied to
the post-run ledger, never to model input.

Every episode is a recorded fresh initialization, not an exact state clone.
Seeds are planner/randomness seeds of the same fixed layout, not different
layouts. The shared ENGINEERING_ORACLE assistance is unchanged. This is not a
formal E1 noninferiority result or a generalization success-rate estimate.

Offline test: `python -m unittest discover -s astra_realman_harness/tests -p test_sim_ms_pilot.py -v`.
Four tests cover raw usage accounting, outcome classification, exact sequence
and caps with a retained legal stop, and immediate batch termination on interface
failure. Tests use no real subprocess, model, physics or hardware.
