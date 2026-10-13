# Pilot 01 — frozen six-scene A/C exploration

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
