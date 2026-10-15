"""Read-only descriptive tables from the archived Batch 01 REAL evidence."""
import csv
import gzip
import hashlib
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / 'run'


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ledger = read(RUN / 'ledger_PUBLIC_SANITIZED.json')
    summary = read(RUN / 'summary.json')
    manifest = read(RUN / 'source_to_archive_manifest.json')
    for row in manifest:
        assert sha(RUN / row['archive_relative_path']) == row['archive_sha256']
        if row['source_relative_path'].endswith('/physics.jsonl'):
            digest = hashlib.sha256(); size = 0
            with gzip.open(RUN / row['archive_relative_path'], 'rb') as f:
                for block in iter(lambda: f.read(1024 * 1024), b''):
                    digest.update(block); size += len(block)
            assert digest.hexdigest() == row['source_sha256'] and size == row['source_bytes']
    native_manifest = read(HERE.parent / 'mac_jobs_manifest.json')
    for row in native_manifest['files']:
        assert sha(HERE.parent / 'mac_jobs' / row['file']) == row['sha256']
    assert ledger['status'] == 'STOPPED' and ledger['reserved_budget'] == 16
    records, threads, requests, jobs = [], [], [], []
    reset_checks = []
    per_episode = {r['episode_id']: r for r in summary['episodes']}
    for reservation in ledger['dispatches']:
        folder = RUN / reservation['artifact']
        response, transport, bridge = (read(folder / p) for p in
                                      ('response.json', 'transport.json', 'bridge_result.json'))
        wire = read(folder / 'bridge_request.json')
        context = wire['context']
        assert sha(folder / 'raw.txt') == hashlib.sha256(response['raw'].encode()).hexdigest()
        assert (folder / 'events.jsonl').read_text() == response['events'] == bridge['events']
        assert response['raw'] == bridge['raw']
        events = [json.loads(line) for line in response['events'].splitlines() if line.strip()]
        started = [e for e in events if e['type'] == 'thread.started']
        completed = [e for e in events if e['type'] == 'turn.completed']
        assert len(started) == len(completed) == 1
        assert not any(e['type'] in ('error', 'turn.failed') for e in events)
        assert 'reconnect' not in (response['events'] + response['stderr']).lower()
        assert response['return_code'] == 0 and response['error'] is None
        assert transport['http_status'] == 200 and transport['dispatch_attempts'] == 1
        assert transport['retries'] == transport['cancel_attempts'] == 0
        assert transport['remote_model_parameter_audit'] == 'PASS'
        command = bridge['command']
        assert '--ephemeral' in command and command[command.index('--model') + 1] == 'gpt-6-astra'
        assert 'model_reasoning_effort="medium"' in command
        jobs.append(command[command.index('--cd') + 1])
        native = HERE.parent / 'mac_jobs' / Path(jobs[-1]).parent.name
        assert read(native / 'command.json') == command
        assert read(native / 'prompt.json') == context
        assert read(native / 'authoritative_schema.json') == wire.get('authoritative_schema', wire['schema'])
        native_result = read(native / 'result.json')
        assert native_result['raw'] == response['raw'] and native_result['events'] == response['events']
        threads.append(started[0]['thread_id']); requests.append(wire['request_id'])
        digest = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False,
                                          allow_nan=False).encode()).hexdigest()
        assert digest == reservation['context_sha256']
        if reservation['decision'] == 1:
            assert context['recent_history'] == []
            reset_checks.append(reservation['episode_id'])
        assert len(context['recent_history']) <= 2
        assert len(context['attachments']) == 4
        for item in context['attachments']:
            assert sha(folder / 'input_only' / item['file']) == item['sha256']
        action = json.loads(response['raw'])
        violation = 'DONE_WITH_ACTIONS' if action['done'] and action['actions'] else None
        assert violation is None or reservation['index'] == 16
        assert (folder / 'receipt.json').exists() == (violation is None)
        receipt = read(folder / 'receipt.json') if violation is None else None
        timing = read(folder / 'timing.json') if (folder / 'timing.json').exists() else {}
        if timing:
            assert timing['inference_physics_steps'] == 0
        usage = response['usage']
        e = per_episode[reservation['episode_id']]
        records.append(dict(global_dispatch=reservation['index'], episode=reservation['episode_id'],
            condition=e['condition_id'], repeat=e['repeat'], decision=reservation['decision'],
            frozen_ledger_request_status=reservation['status'],
            completion_known=True, json_syntax_valid=True,
            action_protocol_valid=violation is None, protocol_error=violation,
            execution=action['execution'], done=action['done'], proposed_arms=[x['arm'] for x in action['actions']],
            receipt_ok=receipt['ok'] if receipt else None, model_action_executed=receipt.get('executed') if receipt else False,
            input_tokens=usage.get('input_tokens'), output_tokens=usage.get('output_tokens'),
            reasoning_output_tokens=usage.get('reasoning_output_tokens'),
            cached_input_tokens=usage.get('cached_input_tokens'),
            cache_write_input_tokens=usage.get('cache_write_input_tokens'),
            client_latency_s=response['wall_latency_s'], native_cli_latency_s=bridge.get('latency_s'),
            execution_physics_steps=timing.get('execution_physics_steps', 0),
            request_id=wire['request_id'], thread_id=started[0]['thread_id'],
            context_sha256=digest, artifact=reservation['artifact']))
    assert len(set(threads)) == len(set(requests)) == len(set(jobs)) == 16
    assert sum(r['action_protocol_valid'] for r in records) == 15
    assert sum(read(RUN / r['artifact'] / 'transport.json')['dispatch_attempts'] for r in records) == 16
    final_ep = read(RUN / 'ep05/episode.json')
    previous_receipt = read(RUN / 'ep05/decision_000/receipt.json')
    assert final_ep['physics_steps'] == previous_receipt['receipts'][-1]['end_step']
    totals = {key: sum(r[key] for r in records) for key in
              ('input_tokens', 'output_tokens', 'reasoning_output_tokens', 'cached_input_tokens', 'cache_write_input_tokens')}
    latencies = [r['client_latency_s'] for r in records]
    metrics = dict(campaign_id=ledger['campaign_id'], status=ledger['status'],
        stop_reason=ledger['stop_reason'], first_dispatch_at=ledger['first_dispatch_at'],
        finished_at=ledger['finished_at'], elapsed_budget_wall_s=ledger['elapsed_wall_s'],
        budget_reservations=16, actual_client_dispatches=16, protocol_valid_outputs=15,
        protocol_invalid_outputs=1, known_completed_requests=16, completion_unknown_requests=0,
        http_failures=0, cli_top_level_errors_or_reconnects=0, automatic_retries=0,
        independent_threads=16, independent_cli_input_only_directories=16,
        started_episodes_with_empty_initial_history=reset_checks,
        tokens_as_reported=totals, cache_hit_requests=sum(r['cached_input_tokens'] > 0 for r in records),
        client_latency_total_s=sum(latencies), client_latency_mean_s=statistics.mean(latencies),
        client_latency_median_s=statistics.median(latencies), client_latency_range_s=[min(latencies), max(latencies)],
        simulation_total_s=sum(e['sim_time_s'] or 0 for e in summary['episodes']),
        valid_decision_count=sum(e['decisions'] for e in summary['episodes']),
        executed_numeric_action_groups=sum(e['executed_action_groups'] for e in summary['episodes']),
        numeric_refusals=sum(e['numeric_refusals'] for e in summary['episodes']),
        parallel_proposals_executed=0,
        invalid_proposal_executed=False, original_main_score_labels_preserved=True,
        manifest_files_verified=len(manifest),
        interpretation='Reported token categories are retained as reported, not converted into internal computation. Client and episode latency include more than model computation. No unexecuted proposal was repaired or simulated.')
    (HERE / 'derived_metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    (HERE / 'per_dispatch.json').write_text(json.dumps(records, indent=2) + '\n')
    with (HERE / 'per_dispatch.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]), lineterminator='\n'); writer.writeheader(); writer.writerows(records)
    episodes = []
    for e in summary['episodes']:
        label = {'SUCCESS': 'PASS', 'TASK_FAILURE': 'FAIL', 'BUDGET_TRUNCATED': 'TRUNCATED',
                 'INFRASTRUCTURE_FAILURE': 'FAIL_PROTOCOL_NOT_SCORED', 'NOT_STARTED': 'NOT_STARTED'}[e['status']]
        episodes.append(dict(episode=e['episode_id'], condition=e['condition_id'], repeat=e['repeat'],
            display_status=label, original_status=e['status'], client_dispatches=e['client_dispatches'],
            protocol_valid_decisions=e['decisions'], actual_numeric_groups=e['executed_action_groups'],
            numeric_refusals=e['numeric_refusals'], inference_wall_s=e['inference_wall_s'],
            simulation_s=e['sim_time_s'], episode_wall_s=e['episode_wall_s'],
            main_score_pass=(e['score'] or {}).get('pass')))
    with (HERE / 'per_episode.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(episodes[0]), lineterminator='\n'); writer.writeheader(); writer.writerows(episodes)
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
