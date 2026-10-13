# Pilot 01 — frozen six-scene A/C exploration

Completed: 24/24 newly authorized dispatches, 23 valid and one original 90-second
timeout. With the preserved historical S5 A, all 24 primary cells / 12 pairs are
complete. Understanding: A 45/54 questions, C 54/54; planning: A and C both 6/6.
Four numerical failures are within a few nanometers of the frozen 5 mm boundary;
scores are preserved and this sensitivity is reported. No extra S5 A repeat was
dispatched because the cumulative budget was exhausted.

Final artifacts: [research report](../evidence/pilot01_parallel180_20261013/research_report.md),
[offline audit](../evidence/pilot01_parallel180_20261013/final_offline_audit.json),
[original stopped phase](../evidence/pilot01_20261013/ledger.json),
[completed 180-second phase](../evidence/pilot01_parallel180_20261013/ledger.json).

User authorization on 2026-10-13 permits at most **24 new dispatches**, sequentially,
through the original Mac ChatGPT bridge. The historical S5 plan A at `0091de8`
is preserved and excluded from the new budget. The primary matrix contains 12 pairs;
the final additional S5 A repeat is reported separately and cannot replace its baseline.

Fixed: gpt-6-astra, medium, openai, ephemeral sessions, 90-second client deadline,
original bridge, original Code Mode flags, frozen SAPIEN data, prompt, schema and scorer.
No real hardware, rerender, model training, automatic retry, fallback model or deadline extension.

`lab/pilot01.py` wraps the existing V0 runner without altering its inference or scoring.
Before any dispatch, it verifies all 24 generic payloads, A/C equality except Oracle geometry,
RGB-D/calibration/GT consistency and the private GT canary. Historical S5 A must exactly
match the current A payload, images, task, schema and parameters. Files are sealed by SHA-256.

Every `next` reserves one unit in an fsynced, atomic, canonical ledger before invoking the
existing runner. A global advisory lock prevents simultaneous Pilot coordinators. It
dispatches exactly one sample and returns. An interrupted IN_FLIGHT record blocks further
requests; reservations are never refunded. The 24-job schedule cannot be changed at runtime.

HTTP failures, cancellation/deadline, unknown completion, absent/duplicate turn.completed,
empty or invalid JSON, changed CLI command/model/Code Mode, reused thread, frozen-input
drift or rescore mismatch stop the whole batch. Startup warning items are retained;
the historical warning-only completed result remains valid. Valid JSON with illegal
geometry is a valid capability result and does not stop the batch. No answer is repaired.

## Commands

On yanglab, from `/home/tongji/alex/spatial-eval-pilot01-20261013`:

```bash
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"
PY=/home/tongji/alex/spatial-eval-lab-20261013/.venv/bin/python
$PY -m unittest discover -s experiments/spatial_input_eval_v0/tests -v
# One-time initialization; refuses an existing canonical output directory.
$PY experiments/spatial_input_eval_v0/lab/pilot01.py init
# Exactly ONE newly authorized request. Stops when failed, interrupted or exhausted.
$PY experiments/spatial_input_eval_v0/lab/pilot01.py next
# Offline summary refresh; zero requests.
$PY experiments/spatial_input_eval_v0/lab/pilot01.py report
```

Run order: S5 plan C, S6 plan A/C; S2/S3/S4 understand A/C; all remaining primary
cells; independent S5 plan A repeat last. Commit checkpoints after each priority stage
(and intermediate pairs). Copy the evidence directory to the matching Mac worktree,
then run `python3 experiments/spatial_input_eval_v0/lab/archive_pilot_native.py` to
collect matched raw native logs. It verifies context/schema/image/result equality,
copies only an explicit artifact allowlist, and never reads credentials or invokes a model.

`evidence/pilot01_20261013/` contains the durable ledger, full preflight file seal,
historical parity audit, independent per-dispatch runs, completion audits, primary results,
per-pair comparisons, repeat results, nonvalid records, failure index and descriptive statistics.

S5/S6 are the main planning tasks. S4 uses a prescribed orientation and does not measure
autonomous orientation choice. Equal binary S5 A/C scores do not establish geometry has no
value. The scenes and related tasks provide exploratory descriptive statistics only;
no significance or population-generalization claim is warranted.

## User amendment after the fourth request

The original 90-second phase stopped after S2 understand A timed out. It used four
dispatches: three valid completions and one timeout. Its ledger remains STOPPED.
The user then explicitly chose **four isolated bridge workers, offline acceptance,
and 180-second deadlines**. The cumulative limit remains 24; the amended phase has
at most 20 dispatches. Completing the primary matrix uses all 20, so the extra S5 A
repeat is omitted unless further authorization is provided. No extra budget is inferred.

`lab/isolated_mac_worker.py` imports the unchanged, SHA-pinned original Handler and
infer implementation in four independent processes. Mac ports 18771–18774 forward
to the same loopback ports on yanglab. The original service on 18767/18766 is untouched.
The bearer token is acquired by the original SSH command into memory, and generation
uses the existing Mac ChatGPT authentication; no auth file is copied. Each request
retains the original CLI command and its independent UUID input/runtime directories.
Only the server timeout option changes to 180. The evaluation adapter's 180-second
limit is opt-in; all existing callers default to 90.

`lab/parallel180.py` has an independent immutable-output phase directory and subtracts
the four prior reservations before scheduling. Each invocation launches one wave of
up to four, with all reservations persisted before dispatch. Any failure sets an abort
flag, sends non-generating cancellation to in-flight peers and stops later waves.
Already dispatched peers still consume budget. Cancellation acknowledgment does not
prove remote model completion. Neither timeout nor invalid output is a geometric zero.

```bash
# On yanglab, using the PYTHONPATH/PY environment above:
$PY experiments/spatial_input_eval_v0/lab/parallel180.py init  # one time only
$PY experiments/spatial_input_eval_v0/lab/parallel180.py wave  # at most four new calls
$PY experiments/spatial_input_eval_v0/lab/parallel180.py report  # offline only
# On Mac, after copying the phase evidence:
python3 experiments/spatial_input_eval_v0/lab/archive_pilot_native.py --phase pilot01_parallel180_20261013
python3 experiments/spatial_input_eval_v0/lab/pilot01_report.py --phase pilot01_parallel180_20261013
```

The four-worker offline protocol reached measured concurrency four with generation
disabled, preserved the frozen schemas/images, and all 68 tests passed. Non-generating
GET checks returned 501 on all eight local/forwarded endpoints, as expected from the
original Handler. Commands/PIDs and source hashes are recorded in service_launch.json
and worker-N.json. Deadline/concurrency phase labels accompany the combined primary
matrix; latency differences across the 90-second serial and 180-second concurrent
phases must not be attributed solely to geometry.

Final offline reproduction (no model or simulator is invoked):

```bash
$PY experiments/spatial_input_eval_v0/lab/finalize_pilot01.py
$PY experiments/spatial_input_eval_v0/lab/pilot01_report.py --phase pilot01_parallel180_20261013
```

The complete ledger blocks any further wave. Do not reset it to replay generation;
the saved responses are sufficient for offline re-scoring and report reproduction.
