# Pilot02 continuation results

Batch `bc2fbd0b683f4190a81945d251372a42`. New client dispatches 8/8; prior client dispatches 12. Status BUDGET_EXHAUSTED.

| Group | A success / valid | C success / valid |
|---|---:|---:|
| restricted_detour | 2/2 | 2/2 |
| autonomous_yaw | 2/2 | 2/2 |

| Original order | Condition | Score | Status / constraint failures | Input / output / reasoning tokens | Wall seconds |
|---:|---|---:|---|---|---:|
| 13 | RGB_ORACLE_3D | 1.0 | VALID:  | 13874 / 122 / 38 | 22.191677949998848 |
| 14 | RGB_MULTI_VIEW | 1.0 | VALID:  | 13202 / 1118 / 1034 | 69.92420413299988 |
| 15 | RGB_MULTI_VIEW | 1.0 | VALID:  | 13208 / 462 / 378 | 38.38073146700117 |
| 16 | RGB_ORACLE_3D | 1.0 | VALID:  | 13865 / 133 / 49 | 20.5093658759979 |
| 17 | RGB_MULTI_VIEW | 1.0 | VALID:  | 13112 / 739 / 678 | 53.50313650099997 |
| 18 | RGB_ORACLE_3D | 1.0 | VALID:  | 13843 / 127 / 62 | 27.256377343001077 |
| 19 | RGB_ORACLE_3D | 1.0 | VALID:  | 13841 / 118 / 58 | 17.66010826099955 |
| 20 | RGB_MULTI_VIEW | 1.0 | VALID:  | 13092 / 992 / 934 | 59.42110370900264 |

Valid geometric failures remain zero; invalid transport/protocol outputs are not capability zeros.
Tokens are reported usage, not exact internal compute. Client wall time includes transport and queuing.
Exploratory descriptive results only; no significance or generalization claims.

Original run12 and original main pairs were not modified or recombined. All continuation results were independently re-read and rescored. Native CLI top-level errors and reconnect events are preserved per row.
