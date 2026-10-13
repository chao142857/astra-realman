# Pilot 02 real batch — stopped at dispatch 12

Execution host was corrected by the user to **ubuntu-robot**. The same cumulative authorization of at most 20 new requests was used; the failed yanglab preflight used zero. Baseline implementation: `e6f0e31`. Batch ID: `953a8d18a01447599664db2170862d98`.

## Production acceptance

The designated host passed 111/111 offline tests and all 607 frozen hashes. The original Mac ChatGPT login was verified. The unchanged original bridge ran in its supported local mode, with a dedicated SSH reverse tunnel to ubuntu-robot, original bearer protocol and a new host-specific transport token stored outside Git. Authentication was verified using an unknown non-generating route (wrong token 403, correct token 404); no `/decide` health call occurred. Model `gpt-6-astra`, reasoning `medium`, Code Mode flags and original production source were unchanged. Single worker, server timeout 190 seconds, client deadline 180 seconds, independent ephemeral sessions.

## Stop reason and budget accounting

The dispatcher reserved and issued **12 HTTP generation requests**, never retried, and never issued request 13. There are **11 valid scored outputs, 1 NOT_SCORED output, 5 complete A/C pairs**, and 8 unused dispatcher slots. Do not treat the unused slots as permission to automatically resume this stopped batch.

Request 12 (`p02_a_m30_plus`, A) emitted a top-level CLI error:

> Reconnecting... 2/5 (stream disconnected before completion: websocket closed by server before response.completed)

The CLI subsequently returned valid-looking JSON, a `turn.completed` event, HTTP 200 and return code 0. The frozen gate intentionally rejects any top-level error, so its persisted label remains `COMPLETION_NOT_CONFIRMED`, score null. This label does **not** mean the completion event was absent in this case. The raw answer is preserved unchanged; it was not promoted to a scored result.

The native CLI performed automatic reconnect handling despite the dispatcher issuing one request and zero retries. Its reconnect counter does not establish the number of upstream model generations. **Actual upstream generation-attempt count is unknown**; only 12 client dispatches are verified. No attempt was made to disable or work around this after the event, change frozen settings, retry, refund or expand the budget. Investigating native reconnect behavior and budget accounting is required before any continuation decision.

The dedicated Pilot02 bridge and tunnel were stopped after the dispatcher stopped. Older workers and Pilot01 ledgers were untouched.

## Geometry success (successes / valid outputs)

| Group | A | C | Coverage |
|---|---:|---:|---|
| 3 mm per-side placement margin | 2/2 | 2/2 | 2 complete pairs |
| 10 mm per-side placement margin | 2/2 | 2/2 | 2 complete pairs |
| 30 mm per-side placement margin | 1/1 | 2/2 | 1 complete pair; one A NOT_SCORED |
| Restricted detour | N/A | N/A | Not dispatched |
| Autonomous yaw | N/A | N/A | Not dispatched |

There were no geometric zero scores among the 11 valid outputs. The protocol failure and unobserved samples are not spatial-capability zeros. All 5 complete pairs have C-minus-A binary score difference 0; this ceiling does not show Oracle geometry is useless.

## Descriptive resources for the 5 complete pairs

| Mean per request | A | C |
|---|---:|---:|
| Input tokens | 13,084.6 | 13,768.6 |
| Output tokens (including reasoning) | 596.2 | 89.6 |
| Reported reasoning tokens | 545.2 | 38.6 |
| Other output tokens | 51.0 | 51.0 |
| Client wall seconds | 41.28 | 20.85 |

One complete pair had a cache hit. Restricting to the 4 pairs without reported cache hits: mean A/C client time 44.58/21.27 seconds, mean reasoning tokens 583.75/38.00. These are exploratory descriptions, not significance tests, generalization claims or exact internal-compute measurements. Client time includes transport and queuing. All-dispatch totals, including the invalid twelfth request, are separately recorded in the JSON report; they are not silently mixed into the paired means.

## Evidence and reproduction

- `evidence/pilot02_runs/pilot02_real_01/`: immutable raw outputs/events, original bridge receipts, input hashes, ledger, bound authorization, per-run assessments/rescores, pair results, `RESEARCH_REPORT.md`, `research_summary.json`, `paired_resource_statistics.json`.
- `evidence/pilot02_ubuntu_production_20261013/`: tests, production checks, shutdown receipt, final audit, 12 original Mac CLI archives and their SHA manifest. Actual Mac model contexts (12) and RGB hashes (36) match frozen inputs exactly. Opaque CLI runtime SQLite state stays on Mac and was not exported; no auth/token file was copied into evidence.
- All 607 sealed artifacts were rechecked after the batch; all 12 archived assessments agree with independent rereading/rescoring. No scorer, threshold, source bridge, model input or Pilot01 result changed.

Read-only report regeneration:

```bash
cd /home/alex/astra-realman_ws/spatial-pilot02-real-20261013
PYTHONPATH=experiments/spatial_input_eval_v0 /home/alex/astra/.venv/bin/python \
  experiments/spatial_input_eval_v0/lab/pilot02_real_report.py \
  --output experiments/spatial_input_eval_v0/evidence/pilot02_runs/pilot02_real_01
```

This command performs no network requests and does not change ledger or original scores. Do not run dispatcher `run --real` or reconcile to bypass the recorded top-level CLI error.
