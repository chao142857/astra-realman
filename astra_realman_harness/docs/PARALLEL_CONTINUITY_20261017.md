# Live parallel continuity v1

Scope: actual GUI → run_parallel_arms → ProcessArmWorker → RealArmExecutor. No model or hardware requests during implementation. No task routes, target repair, object-state inference, safety-threshold change or expert policy.

Input now contains the last 8 completed measured transitions, chronological with explicit older-count truncation. Raw model summaries/intents are labelled model_judgment, separate from measured before/after controller poses, joint states, opening, actual XYZ delta, dispatched commands, failures and IK rejection feedback. No historical images are attached; the prompt explicitly states this. No previous-episode history is loaded. Grasp and object motion remain UNKNOWN; SDK completion/opening/TCP motion are not object-grasp evidence.

Per-arm execution is unchanged: TCP command → readback/guard → gripper command if needed. Models must split close-then-lift decisions. Parallel is between independent arms, not synchronized grasp control. No automatic sequencing/waypoint changes.

Only ProcessArmWorker opts into 1/1000 raw opening-count tolerance. A healthy, stationary feedback of 399 satisfies a target of 400; 398 or moving/error feedback does not. Target itself is preserved. Skip reason, command-time TCP (when gripper is actually sent), before/after opening evaluation and UNKNOWN grasp are journalled. Other legacy callers retain exact-equality default. This does not implement contact/force servo or declare grasp success.

Mac + yanglab: 56 parallel/mock regression tests PASS, including inherited executor tests for IK, command errors, frame changes, retries and gripper feedback. New tolerance integration verifies arm motion still occurs while redundant gripper command is skipped. No SDK imported by replay.

Offline replay on yanglab:

```
cd /home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness
/home/tongji/miniconda3/envs/dp/bin/python -B scripts/replay_parallel_history.py \
 --run logs/parallel-arms-20261017T101344-be0acc23 \
 --output logs/parallel-history-offline-v1-20261017
```

Output already exists; use a fresh output directory to repeat. 47 complete transitions replayed; step 48 incomplete excluded. Explicit windows 12–13,25–29,41–45 exported with pre-decision history. Step 25 close at z≈0.2207 m then step 26 measured +0.024994 m; step 41 then42 +0.025011 m. This is TCP displacement only. Original source/results unchanged. Raw logs/media remain on yanglab, not pushed.

Remaining live questions: whether longer history reduces repeated unsupported attempts, actual one-count jitter behavior under load, and visually confirmed grasp. Eight-step history intentionally forgets older details. Existing lack of common-base calibration/shared collision certification is unchanged. No new run started or old STOPPED run resumed.

Also preserves the previously staged stop-signal fix: signal handler sets a simple flag; a separate thread relays to multiprocessing.Event to avoid re-entering its lock. This is not hardware emergency stop and cannot repair an already stuck process in-place.
