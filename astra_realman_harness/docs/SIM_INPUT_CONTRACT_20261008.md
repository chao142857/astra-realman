# Fixed-scene placement input contract follow-up

Base: `f7c8da11867aca6743def410699ca9061691cb46`. This is an additive follow-up;
the frozen commit and its delivery archive remain unchanged.

The previous final model payload referred to an offered action but omitted its
definition. Both M and S now receive the same public action catalog, all existing
targets, units, frame, tool, revision, pose source, applicability, and complete
four-primitive expansion from the shared `placement_primitives` generator.
M's approval request identifies the current primitive and its zero-based index.
S's approval request identifies the complete `fixed_green_marker_place_v1` skill
and all four indices. The output remains exactly `{binding, action}`, where
action is `continue` or `stop`; the observation/revision binding is unchanged.

`sim_skills/contract.py` builds the prospective description without accessing the
scene, contact state or evaluator. The final `input_payload` projection checks
catalog structure, expansion, revision and approval scope before the worker is
invoked. Unexpected catalog fields and stale offers fail before a model call.
Object truth, contact truth, terminal scores and future results are not added.

Physics assets, backend, controller, targets, primitive generator, common checks,
budget boundaries, CLI worker and no-retry behavior are unchanged. Initialization
and holding checks still use the declared ENGINEERING_ORACLE assistance. The
catalog describes commands; it does not promise that the object will be placed.

Offline validation command (from the repository root):

```bash
PYTHONDONTWRITEBYTECODE=1 /home/alex/astra/.venv/bin/python -m unittest discover -s astra_realman_harness/tests -p test_sim_skills.py -v
```

Result: 29 tests passed. Added tests inspect final M/S worker payloads, assert
identical catalogs and matching executed test-double commands, reject stale or
injected offers before the worker, exclude truth/future sentinels, and preserve
valid stop with zero subsequent checks/actions/evaluation. The real worker also
runs against a local fake CLI that validates the JSON received on stdin and the
input-only attachments. These tests make no real model or hardware calls.

Offline receipts are under `/tmp/astra-model-once-evidence-20261008/`:
`offline-tests.log`, `offline-acceptance.json`, and `offline-final-payload/`.
The acceptance receipt checks frozen hashes for the backend, targets, generator,
entrypoint and CLI worker, all 56 asset manifest entries, and executable AST
equivalence of model/runtime outside the input-contract additions.

The authorized subsequent run is at most one top-level local CLI request:
S, requested `gpt-6-astra` / `medium`, 120 seconds, existing START_HERE assets,
fresh output directory. No retry follows stop, timeout or parse failure. Its
result must separately report interface acceptance, model choice, physical
execution/evaluation, and counts/failures. Server identity, effort and internal
retry counts remain unknown unless explicitly returned. This run is only fixed
engineering scene channel validation, not an E1 performance conclusion.
