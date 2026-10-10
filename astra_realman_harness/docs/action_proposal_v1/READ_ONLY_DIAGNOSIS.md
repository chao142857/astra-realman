# Frozen real A: layered read-only diagnosis

Source: `candidate-v2-a-h4-authorized-01-20261010/RAW_RESPONSE.json`, original rm65:0002 input and W2. Full raw text and unchanged decoded waypoint/assumption/precondition records accompany this report. No corrected answer or plan is created.

| Point | Original x (m) | Original y (m) | Original z (m) | Distance from original predecessor (mm) | Orientation change (rad) |
|---|---:|---:|---:|---:|---:|
| 1 | 0.319878565 | -0.020037056 | 0.1500088265463092 | 1020.229170 | 0 |
| 2 | 0.339676647 | -0.040075329 | 0.1500088265463092 | 28.169069 | 0 |
| 3 | 0.35947472931529223 | -0.06011360282030444 | 0.1500088265463092 | 28.169070 | 0 |
| 4 | 0.35947472931529223 | -0.06011360282030444 | 0.1200088265463092 | 30.000000 | 0 |

Every waypoint has original quaternion wxyz:
`[-4.095491021871567e-06, 1, 3.328512320877053e-05, 0.0001482087536714971]`.
Nominal times are `[2,4,6,8]` seconds; prefix dependencies are `[],[1],[1,2],[1,2,3]`. First three boundaries are `none`, last `precontact_handoff`.

**Runtime state echo error:** raw origin Y=1 m, measured Y=0.000001216949936296409 m. Other origin components match. Translation echo error is 999.998783 mm. From the actual measured origin, independent WP1 distance is 28.169069 mm. This alternative calculation is not a plan repair or a new pass.

**Action geometry / stage contract:** with the raw origin, WP1 violates 50 mm. Remaining translations and orientation deltas satisfy those individual step limits. A separate termination error remains: `horizon_filled` conflicts with the final `precontact_handoff` under unchanged v2 validation. The model's three lateral increments and final descent are numerically meaningful against the real origin, but this does not waive either failure.

**Endpoint versus observed object_004:** observed bounds are
`[[0.33468566349777595,-0.08549343022759015,0.006682179482214759], [0.38426379513280856,-0.03473377541301873,0.05115007070002489]]` m.
Endpoint XY lies inside these bounds and coincides with the observed-bounds midpoint XY; endpoint Z is 68.858756 mm above the observed maximum Z, or 91.092701 mm above the support representative. These are observed surface relationships, not object-complete geometry, free space or collision clearance.

**Evidence declaration errors:** WP1 `current_geometry` and `measured_join` say `supported_by_input` with empty evidence_refs. The original validator rejects them independently. Listing a condition or choosing a sensible coordinate cannot supply the missing citation. Original assumptions, all 20 condition declarations and unknowns are preserved verbatim in DIAGNOSIS.json / ORIGINAL_MODEL_RAW.txt.

Conclusion remains **FAIL_STOP_LOCAL_OUTPUT_CONTRACT**. IK, collision and clearance are **NOT_TESTED**; K=0; no execution eligibility. The generic old worker failure-stage label is not a transport-failure diagnosis; local output validation rejected the answer after a real raw was returned. Original files and labels remain unchanged.
