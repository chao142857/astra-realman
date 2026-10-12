# Astra spatial input evaluation V0

Recorded samples: 4; real model attempts started: 0.
Mock results verify plumbing only; no claim of Astra capability or significance.

| Condition | Rows | Scored | Mean score |
|---|---:|---:|---:|
| RGB_MULTI_VIEW | 2 | 2 | 0.0 |
| RGB_RECON_3D | 0 | 0 | UNKNOWN |
| RGB_ORACLE_3D | 2 | 2 | 0.0 |

Paired comparisons (right minus left):

- RGB_MULTI_VIEW → RGB_RECON_3D: n=0, mean delta=UNKNOWN.
- RGB_MULTI_VIEW → RGB_ORACLE_3D: n=2, mean delta=0.0.
- RGB_RECON_3D → RGB_ORACLE_3D: n=0, mean delta=UNKNOWN.

Significance: NOT_ESTABLISHED. V0 reports paired descriptive differences only; repeated scenes/tasks are not independent replicates.

See `failure_index.json` and each request/response/evaluation artifact for the exact failed constraint.
