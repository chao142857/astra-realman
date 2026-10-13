# Pilot 02 real batch results

Batch `953a8d18a01447599664db2170862d98`; status **STOPPED**; reserved 12/20. Valid 11; NOT_SCORED 1; complete A/C pairs 5.

| Group | A successes / valid | C successes / valid |
|---|---:|---:|
| placement_3mm | 2/2 | 2/2 |
| placement_10mm | 2/2 | 2/2 |
| placement_30mm | 1/1 | 2/2 |
| restricted_detour | N/A (no valid samples) | N/A (no valid samples) |
| autonomous_yaw | N/A (no valid samples) | N/A (no valid samples) |

## Per-dispatch evidence

| # | Scene | A/C | Status | Score | Input / output / reasoning tokens | Wall seconds | Failure |
|---|---|---|---|---:|---|---:|---|
| 1 | p02_a_m03_minus | RGB_MULTI_VIEW | VALID | 1.0 | 13082 / 585 / 534 | 31.60848640599943 |  |
| 2 | p02_a_m03_minus | RGB_ORACLE_3D | VALID | 1.0 | 13790 / 88 / 37 | 22.369312029000866 |  |
| 3 | p02_a_m03_plus | RGB_ORACLE_3D | VALID | 1.0 | 13765 / 95 / 44 | 19.36607358999936 |  |
| 4 | p02_a_m03_plus | RGB_MULTI_VIEW | VALID | 1.0 | 13087 / 715 / 664 | 53.90742398800103 |  |
| 5 | p02_a_m10_minus | RGB_ORACLE_3D | VALID | 1.0 | 13768 / 92 / 41 | 21.864433652001026 |  |
| 6 | p02_a_m10_minus | RGB_MULTI_VIEW | VALID | 1.0 | 13075 / 413 / 362 | 34.025802355999986 |  |
| 7 | p02_a_m10_plus | RGB_MULTI_VIEW | VALID | 1.0 | 13076 / 826 / 775 | 58.760433620000185 |  |
| 8 | p02_a_m10_plus | RGB_ORACLE_3D | VALID | 1.0 | 13759 / 81 / 30 | 21.47017944899926 |  |
| 9 | p02_a_m30_minus | RGB_MULTI_VIEW | VALID | 1.0 | 13103 / 442 / 391 | 28.107340131000456 |  |
| 10 | p02_a_m30_minus | RGB_ORACLE_3D | VALID | 1.0 | 13761 / 92 / 41 | 19.17390556600003 |  |
| 11 | p02_a_m30_plus | RGB_ORACLE_3D | VALID | 1.0 | 13764 / 88 / 37 | 18.71349030300007 |  |
| 12 | p02_a_m30_plus | RGB_MULTI_VIEW | NOT_SCORED | None | 13071 / 718 / 667 | 109.57819774400014 | COMPLETION_NOT_CONFIRMED |

No missing/invalid output is counted as a geometry zero.
Descriptive pilot results only; no significance or generalization claims.
Null reasoning/cache tokens mean not reported, not zero. Tokens are usage, not exact internal compute.
Client wall time includes transport and any cancellation; not pure model compute time.
All raw predictions and frozen scoring thresholds unchanged.
A top-level CLI error is disqualifying even if JSON and turn.completed later appear. Native CLI reconnection is distinct from dispatcher retry (zero); upstream generation attempts cannot be inferred from its reconnect counter.

Every row was independently re-read and rescored against its original archived assessment.
