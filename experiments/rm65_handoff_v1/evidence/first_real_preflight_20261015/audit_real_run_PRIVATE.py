"""One-run post-hoc audit only; no transport or model invocation."""
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from action_interface import accept_result, validate_context
from evaluate_transfer import assess
from evaluate_process import evaluate

batch = Path(sys.argv[1]).resolve()
ledger = json.loads((batch / 'ledger.json').read_text())
assert ledger['reserved_budget'] == len(ledger['runs']) <= 16
assert sum(r['stage'] == 'shadow' for r in ledger['runs']) == 1
assert sum(r['stage'] == 'execute' for r in ledger['runs']) <= 15
rows = []
for r in ledger['runs']:
    p = batch / r['artifact']
    item = dict(r)
    if r['status'] == 'VALID':
        action = accept_result(p)
        wire = json.loads((p / 'bridge_request.json').read_text())
        context = wire['context']
        images = [p / 'input_only' / f'image-{i}.png' for i in range(4)]
        # Transport's local archived attachments have these same exact bytes.
        if not all(x.exists() for x in images):
            images = [p / f'image-{i}.png' for i in range(4)]
        validate_context(context, images)
        assert hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest() == r['context_sha256']
        response = json.loads((p / 'response.json').read_text())
        item.update(proposal=action, usage=response.get('usage'), client_wall_s=response['wall_latency_s'],
                    receipt=json.loads((p / 'receipt.json').read_text()),
                    timing=json.loads((p / 'timing.json').read_text()))
        assert item['timing']['inference_physics_steps'] == 0
        events = [json.loads(x) for x in response['events'].splitlines() if x.strip()]
        item['native_item_warnings'] = [e for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'error']
    rows.append(item)
assert len({r['thread_id'] for r in rows if r['status'] == 'VALID'}) == sum(r['status'] == 'VALID' for r in rows)
assessments = {}
for stage in ('shadow_01', 'execute_01'):
    p = batch / stage
    if not (p / 'episode.json').exists():
        continue
    episode = json.loads((p / 'episode.json').read_text())
    raw = p / 'physics.jsonl'
    data = raw.read_text() if raw.exists() else gzip.decompress(raw.with_suffix('.jsonl.gz').read_bytes()).decode()
    physics = [json.loads(x) for x in data.splitlines() if x.strip()]
    dt = json.loads((p / 'configuration.json').read_text())['dt']
    result = assess(physics, dt)
    assert result == episode['private_physical_assessment'], stage
    (p / 'independent_transfer_assessment_v1.json').write_text(json.dumps(result, indent=2) + '\n')
    # The original legacy evaluator reads the original uncompressed remote log.
    legacy = evaluate(p) if raw.exists() else None
    assessments[stage] = {'exact_independent_rescore_match': True, 'episode_status': episode['status'],
                          'new_transfer_assessment': result, 'legacy_evaluator_unmodified_result': legacy,
                          'legacy_note': 'Original velocity thresholds and placement checks are unchanged. Its hardcoded model_calls=0 is not request accounting; use this batch ledger. Placement is outside this task.'}
    if legacy is not None:
        (p / 'legacy_process_evaluation_UNMODIFIED.json').write_text(json.dumps(legacy, indent=2) + '\n')
for stage in ('shadow_01', 'execute_01'):
    p = batch / stage / 'decision_000' / 'bridge_request.json'
    if p.exists():
        assert json.loads(p.read_text())['context']['recent_history'] == []
report = {'batch_id': ledger['batch_id'], 'status': ledger['status'],
          'client_dispatches': ledger['reserved_budget'], 'upstream_generation_count': 'UNKNOWN_NOT_CLIENT_CONTROLLABLE',
          'decisions': rows, 'assessments': assessments,
          'shadow_not_in_execute_initial_history': True,
          'client_latency_note': 'Includes bridge/CLI/network overhead; not pure model compute time.',
          'reported_token_note': 'Reported reasoning tokens are supplementary, not exact internal computation.'}
(batch / 'independent_audit_PRIVATE.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'batch_id': ledger['batch_id'], 'client_dispatches': ledger['reserved_budget'],
                  'status': ledger['status'], 'independent_rescores': {k: v['exact_independent_rescore_match'] for k, v in assessments.items()}}, indent=2))
