"""Post-hoc checks of this completed batch. No network, dispatch or simulation."""
import csv
import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
BATCH = TASK / 'evidence/workspace_runs/first_workspace_20261015_01'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = read(BATCH / 'ledger.json')
    original = read(BATCH / 'authorization_REQUEST_NOT_GRANTED.json')
    granted = read(BATCH / 'authorization_GRANTED.json')
    assert {k for k in original if original[k] != granted[k]} == {
        'generation_authorized', 'max_dispatches', 'user_authorization_statement'}
    assert granted['generation_authorized'] is True and granted['max_dispatches'] == 8
    assert granted['source_hashes'] == state['source_hashes']
    assert state['batch_id'] == '8ab36cee132046909da2285fde4b4bc3'
    assert state['status'] == 'FINISHED' and state['reserved_budget'] == 5
    assert len(state['runs']) == 5 and state['shadow_validated']
    assert [r['stage'] for r in state['runs']] == ['shadow'] + ['execute'] * 4
    assert all(r['status'] == 'VALID' for r in state['runs'])
    shadow = read(BATCH / 'shadow_01/episode.json')
    episode = read(BATCH / 'execute_01/episode.json')
    score = read(BATCH / 'execute_01/independent_workspace_score.json')
    assert score == episode['private_physical_assessment'] and score['pass']
    assert shadow['status'] == 'SHADOW_VALID_NO_EXECUTION'
    assert episode['status'] == 'MODEL_STOP_REQUEST_NOT_AUTOMATIC_SUCCESS'
    assert episode['terminal_hold_end_step'] - episode['terminal_hold_start_step'] == 500
    assert episode['numeric_refusals'] == 0
    assert (BATCH / 'shadow_01/initialization_PRIVATE.json').read_bytes() == (
        BATCH / 'execute_01/initialization_PRIVATE.json').read_bytes()
    assert (BATCH / 'shadow_01/workspace_public_policy.json').read_bytes() == (
        BATCH / 'execute_01/workspace_public_policy.json').read_bytes()

    old = TASK / 'evidence/transfer_runs/first_real_1100_20261015_01/ledger.json'
    old_sha = '2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1'
    assert sha(old) == old_sha
    for entry in read(BATCH / 'lossless_physics_archive.json'):
        data = gzip.decompress((BATCH / entry['lossless_copy']).read_bytes())
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        if (BATCH / entry['original']).exists():
            assert data == (BATCH / entry['original']).read_bytes()

    rows, previous, threads, requests, used_jobs = [], [], set(), set(), set()
    warnings = []
    for run in state['runs']:
        folder = BATCH / run['artifact']
        timing = read(folder / 'timing.json')
        result = read(folder / 'bridge_result.json')
        proposal = read(folder / 'proposal.json')
        receipt = read(folder / 'receipt.json')
        job_id = Path(result['local_log']).name
        mac = HERE / 'mac_raw_jobs' / job_id
        mac_result = read(mac / 'result.json')
        assert mac_result['return_code'] == 0 and mac_result['error'] is None
        assert json.loads(mac_result['raw']) == proposal
        assert (mac / 'events.jsonl').read_bytes() == (folder / 'events.jsonl').read_bytes()
        events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
        assert not any(e['type'] in ('error', 'turn.failed') for e in events)
        starts = [e['thread_id'] for e in events if e['type'] == 'thread.started']
        completed = [e for e in events if e['type'] == 'turn.completed']
        assert starts == [run['thread_id']] and len(completed) == 1
        assert run['thread_id'] not in threads and run['request_id'] not in requests
        threads.add(run['thread_id']); requests.add(run['request_id']); used_jobs.add(job_id)
        cmd = mac_result['command']
        assert '--ephemeral' in cmd and cmd[cmd.index('--model') + 1] == 'gpt-6-astra'
        assert 'model_reasoning_effort="medium"' in cmd
        assert timing['inference_physics_steps'] == 0
        assert timing['usage'] == completed[0]['usage']
        context = read(mac / 'prompt.json')
        assert read(mac / 'input_only/context.json') == context
        assert context['recent_history'] == ([] if run['stage'] == 'shadow' else previous[-2:])
        assert len(context['attachments']) == 4
        assert set(context['observations']['calibration']) == {
            'overhead', 'tabletop_front', 'left_wrist', 'right_wrist'}
        assert set(context) == {'instruction', 'conventions', 'output_schema', 'observations',
                                'recent_history', 'attachments', 'task_policy'}
        assert context['task_policy'] == read(BATCH / 'execute_01/workspace_public_policy.json')
        def check_keys(value):
            if isinstance(value, dict):
                assert not {'ground_truth', 'oracle', 'witness', 'private_physical_assessment',
                            'initialization_PRIVATE', 'negative_control'}.intersection(value)
                for child in value.values(): check_keys(child)
            elif isinstance(value, list):
                for child in value: check_keys(child)
        check_keys(context)
        for i, attachment in enumerate(context['attachments']):
            a, b = mac / f'input_only/image-{i}.png', folder / f'input_only/image-{i}.png'
            assert sha(a) == sha(b) == attachment['sha256']
        for e in events:
            if e['type'] == 'item.completed' and e['item']['type'] == 'error':
                warnings.append({'dispatch': run['index'], 'message': e['item']['message']})
        u = timing['usage']
        row = {'dispatch': run['index'], 'stage': run['stage'], 'artifact': run['artifact'],
               'request_id': run['request_id'], 'thread_id': run['thread_id'], 'mac_job_id': job_id,
               'input_tokens': u['input_tokens'], 'cached_input_tokens': u['cached_input_tokens'],
               'cache_write_input_tokens': u['cache_write_input_tokens'],
               'reported_output_tokens': u['output_tokens'],
               'reported_reasoning_output_tokens': u['reasoning_output_tokens'],
               'inference_wall_s': timing['inference_wall_s'],
               'mac_cli_subprocess_wall_s': mac_result['latency_s'],
               'whole_step_wall_s': timing['whole_step_wall_s'],
               'execution_physics_steps': timing['execution_physics_steps'],
               'execution_sim_s': timing['execution_physics_steps'] * .004,
               'done': proposal['done'], 'execution': proposal['execution'],
               'action_count': len(proposal['actions']), 'receipt_ok': receipt['ok'],
               'executed': receipt['executed'], 'proposal_modified': False,
               'context_sha256': run['context_sha256']}
        rows.append(row)
        if run['stage'] == 'execute': previous.append({'proposal': proposal, 'receipt': receipt})
    assert len(used_jobs) == len(list((HERE / 'mac_raw_jobs').iterdir())) == 5
    with (HERE / 'dispatch_metrics.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); w.writeheader(); w.writerows(rows)
    totals = {}
    for stage, selected in [('shadow', rows[:1]), ('execute', rows[1:]), ('all', rows)]:
        totals[stage] = {k: sum(r[k] for r in selected) for k in (
            'input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
            'reported_output_tokens', 'reported_reasoning_output_tokens',
            'inference_wall_s', 'mac_cli_subprocess_wall_s', 'whole_step_wall_s')}
        totals[stage]['dispatches'] = len(selected)
    preflight = read(BATCH / 'production_preflight_FRESH.json')
    ages = [(datetime.fromisoformat(r['reserved_at']) -
             datetime.fromisoformat(preflight['checked_at'])).total_seconds() for r in state['runs']]
    assert all(0 <= age <= 900 for age in ages)
    summary = {'batch_id': state['batch_id'], 'baseline': '2023f98', 'status': 'FINISHED',
               'budget': {'authorized': 8, 'reserved': 5, 'shadow': 1, 'execute': 4,
                          'unused': 3, 'resumption_allowed': False},
               'independent_score_equal': True, 'pass': score['pass'], 'checks': score['checks'],
               'totals': totals, 'dispatches': rows, 'cli_item_warnings': warnings,
               'preflight_age_at_dispatch_s': ages,
               'shadow_not_executed': True, 'fresh_reset_same_initialization': True,
               'execute_initial_history_empty': True, 'unique_ephemeral_threads': 5,
               'matching_input_image_hashes': 20, 'old_ctag_ledger_sha256': old_sha,
               'final_hold_sim_s': 2, 'episode_sim_s_including_initialization': episode['sim_time_s'],
               'task_sim_s': (episode['physics_steps']-episode['task_start_step'])*.004,
               'observation_time_note': 'Client and Mac subprocess times include waiting and overhead; neither is pure model compute time. Physics paused during each inference.',
               'token_note': 'CLI-reported usage retained by field; tokens are not precise internal computation measurements.',
               'scope': 'One fixed scene, sequential coordination. No parallel coordination, real-time reaction or general success-rate conclusion.'}
    (HERE / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'pass': summary['pass'], 'budget': summary['budget'], 'totals': totals}, indent=2))


if __name__ == '__main__': main()
