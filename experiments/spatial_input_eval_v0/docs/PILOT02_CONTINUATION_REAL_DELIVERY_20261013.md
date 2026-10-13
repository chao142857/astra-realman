# Pilot 02 continuation delivery — 2026-10-13

Completed all eight authorized client dispatches, original frozen orders 13–20, from baseline `8a071276dc45f0919b2296e9491279271cbbd2c7`. No further dispatch is authorized by this exhausted grant.

New batch `bc2fbd0b683f4190a81945d251372a42` references original batch `953a8d18a01447599664db2170862d98`, its 12 prior client dispatches, original order SHA `3954819dcf2d2aa3be37c6b35d2b56f6bda9d93416d9ed0d91f463eebe00faa4`, and continuation manifest SHA `2df52de971fdb2759b56ede59a346f2362331c1bd4fbaae73685c00d382f7d5e`. New ledger terminal state is `BUDGET_EXHAUSTED`: all eight completed validly and the eight-dispatch cap was reached.

## Production checks and preservation

- Execution host: ubuntu-robot; dedicated Mac ChatGPT bridge and SSH reverse tunnel. Fresh batch-bound preflight passed before dispatch.
- Unchanged original bridge source/authentication/model/Code Mode; gpt-6-astra, medium, independent ephemeral sessions, single worker, client 180 seconds and server 190 seconds.
- Non-generating authentication checks: wrong token 403, authenticated unknown route 404; no `/decide` health probe. Original CLI version/help and ChatGPT login checks were non-generating.
- Seven continuation offline tests passed; 607 frozen hashes and 212 original batch file hashes passed, including the original live Linux batch.
- Eight distinct new thread IDs; eight dispatch attempts, zero dispatcher retries; no observed native CLI top-level errors or reconnect events in this continuation.
- Original order 12 was not resent. Original STOPPED ledger and NOT_SCORED label remain unchanged. Its post-hoc geometry does not enter these results or primary pairs.
- Independent archived-output reassessment agrees for all eight. All 120 exported Mac CLI evidence files match their manifest; eight actual contexts and 24 actual RGB attachments match frozen inputs, including public task_policy. No authentication files were exported.
- This batch's dedicated Mac bridge and tunnel were shut down after completion; shutdown evidence is archived. No physical hardware was contacted.

## Results

| Group | A success / valid | C success / valid |
|---|---:|---:|
| Restricted detour, two scenes | 2/2 | 2/2 |
| Autonomous yaw, two scenes | 2/2 | 2/2 |

All eight outputs were valid and scored 1.0, with no failed geometric constraints. Four complete A/C pairs have C minus A score difference zero. New invalid outputs and infrastructure failures: zero. Original and continuation batches together contain 19 valid outputs and nine complete primary pairs; the original twelfth output remains excluded. No old main report or scoring was rewritten.

### Reported resources, means per request

| Pair subset | Condition | Input tokens | Output tokens | Reasoning tokens | Client wall seconds |
|---|---|---:|---:|---:|---:|
| All four pairs | A | 13153.50 | 827.75 | 756.00 | 55.31 |
| All four pairs | C | 13855.75 | 125.00 | 51.75 | 21.90 |
| Three pairs excluding cache-hit pair | A | 13167.33 | 857.33 | 782.00 | 55.91 |
| Three pairs excluding cache-hit pair | C | 13860.00 | 124.33 | 48.33 | 20.12 |

`p02_c_slot_030` is the pair with reported cache hits. Output tokens include reasoning; mean remaining output across all pairs is A 71.75, C 73.25 tokens. Full per-request reported usage, raw events, latencies and paired differences are archived. These are small-sample exploratory descriptions, not significance, generalization or causal claims. Tokens do not measure exact internal computation, and client wall time includes transport and queuing. Equal binary scores do not establish that Oracle geometry is useless.

Cumulative client dispatches are 12 + 8 = 20. Client dispatch accounting and native CLI internal reconnects are distinct: the exact upstream generation count is not independently measurable from this ledger. The absence of observed reconnects in the new eight does not make client accounting a general control of upstream attempts.

## Evidence and read-only reproduction

Relative to `experiments/spatial_input_eval_v0`:

- `evidence/pilot02_runs/pilot02_continuation_01/`: new grant, ledger, all raw run artifacts, independent rescoring, pair results, `continuation_summary.json`, `CONTINUATION_REPORT.md`, and `uncached_pair_resources.json`.
- `evidence/pilot02_continuation_production_20261013/`: production preflight, offline test log, final preservation audit, frozen payload audit, shutdown record, and Mac CLI archive manifest/files.

Rebuild only the continuation report, without any generation or ledger change:

```bash
cd /home/alex/astra-realman_ws/spatial-pilot02-continuation-real-20261013
PYTHONPATH=experiments/spatial_input_eval_v0:experiments/spatial_input_eval_v0/lab \
  /home/alex/astra/.venv/bin/python \
  experiments/spatial_input_eval_v0/lab/pilot02_continuation_report.py \
  --output experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_continuation_01
```
