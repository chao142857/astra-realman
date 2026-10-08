#!/usr/bin/env python3
"""Four fixed-scene episodes; ledger only, using the unchanged single-run entrypoint."""
import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

SPECS = ((2, 'M', 4), (2, 'S', 1), (3, 'S', 1), (3, 'M', 4))
SCOPE = '固定场景调度与成本小批检查'


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def usage_totals(usages):
    """Sum only like-named numeric fields across requests; never sum parent and child fields."""
    sums = {}
    def add(dst, src):
        for key, value in src.items():
            if type(value) in (int, float):dst[key] = dst.get(key, 0) + value
            elif isinstance(value, dict):add(dst.setdefault(key, {}), value)
    for usage in usages:
        if isinstance(usage, dict):add(sums, usage)
    return {'sum_of_observed_same_fields': sums, 'complete': all(isinstance(x, dict) for x in usages),
            'missing_usage_requests': sum(x is None for x in usages), 'raw_per_request': usages}


def classify(result, requests, events, return_code):
    """Only valid policy stop or a terminal task score may allow the next episode."""
    p = result.get('placement', {})
    if not p:return 'ABORT_INITIALIZATION', True
    if any(r.get('metadata', {}).get('status') != 'COMPLETE' for r in requests):
        return 'ABORT_INTERFACE', True
    if result.get('model_calls') != len(requests) or p.get('model_attempts') != len(requests):
        return 'ABORT_ACCOUNTING', True
    if any(e['kind'] == 'FINAL_OBSERVATION_FAILED' for e in events):return 'ABORT_EXECUTION', True
    evaluations = [e['data'] for e in events if e['kind'] == 'INDEPENDENT_EVALUATION']
    choices = [(r.get('parsed') or {}).get('action') for r in requests]
    if any(c not in ('continue', 'stop') for c in choices) or 'stop' in choices[:-1]:
        return 'ABORT_PROTOCOL', True
    error = p.get('error') or result.get('error')
    if error == 'RuntimeError:POLICY_STOP' and requests and choices[-1] == 'stop' and not evaluations and return_code == 1:
        return 'STOP', False
    if error:return 'ABORT_EXCEPTION', True
    if len(evaluations) == 1 and 'stop' not in choices and evaluations[0]['status'] == result.get('status') == p.get('status'):
        if result['status'] == 'PASS' and return_code == 0:return 'PASS', False
        if result['status'] == 'FAIL' and return_code == 1:return 'TASK_FAIL', False
    return 'ABORT_INCOMPLETE', True


def summarize(episode, return_code):
    result = read(episode/'result.json', {})
    events = lines(episode/'placement/events.jsonl')
    requests = []
    for folder in sorted((episode/'placement').glob('request-*')):
        metadata = read(folder/'metadata.json', {})
        response = read(folder/'response.json', {})
        context = read(folder/'input_context.json', {})
        requests.append({'request': folder.name, 'metadata': metadata,
            'policy_latency_s': metadata.get('backend_latency_s'), 'worker_latency_s': response.get('latency_s'),
            'usage': metadata.get('usage'), 'raw': response.get('raw'), 'parsed': read(folder/'parsed.json'),
            'command': response.get('command'), 'response_error': response.get('error'),
            'response_return_code': response.get('return_code'),
            'raw_usage_events': [e.get('usage') for e in map(json.loads,response.get('events','').splitlines()) if e.get('type') == 'turn.completed'],
            'attachments': context.get('images_in_attachment_order'), 'local_log': response.get('local_log')})
    status, abort = classify(result, requests, events, return_code)
    p = result.get('placement', {})
    actions = [e['data']['primitive'] for e in events if e['kind'] == 'SKILL_INTERNAL_ACTION']
    evaluations = [e['data'] for e in events if e['kind'] == 'INDEPENDENT_EVALUATION']
    observations = [e for e in events if e['kind'] == 'OBSERVATION']
    phases = lines(episode/'scene/phases.jsonl')
    init = next((e for e in phases if e['phase'] == 'INITIALIZING'), None)
    first = observations[0] if observations else None
    boundary = next((e for e in phases if first and e['phase'] == 'OBSERVE_ENTER' and e['sim_step'] == first['physics_step']), None)
    start = {'reset': result.get('reset'), 'scene_initial_object_private': read(episode/'scene/initial_object_private.json'),
             'initial_observation': result.get('initial_observation'), 'placement_start_observation': first,
             'scope': 'POST_RUN_LEDGER_ONLY; not sent to model; not exact state cloning'}
    (episode/'start-ledger.json').write_text(json.dumps(start, indent=2)+'\n')
    return {'status': status, 'abort_batch': abort, 'runner_status': result.get('status'),
            'actual_requests': result.get('model_calls'), 'requests': requests,
            'usage': usage_totals([x['usage'] for x in requests]),
            'placement_wall_s': p.get('wall_time_s'), 'placement_physics_s': p.get('physics_time_s'),
            'initialization_wall_s': boundary['monotonic_time']-init['monotonic_time'] if init and boundary else None,
            'initialization_timing_definition': 'scene INITIALIZING to first placement OBSERVE_ENTER; excludes preflight/imports; derived existing monotonic events',
            'initialization_physics_s': first['physics_step']*result['dt'] if first else None,
            'nonplacement_wall_s': result['wall_time_s']-p['wall_time_s'] if p else result.get('wall_time_s'),
            'total_runner_wall_s': result.get('wall_time_s'), 'total_physics_s': result.get('physics_time_s'),
            'primitive_sequence': actions, 'executed_sequence_sha256': digest(actions),
            'offered_sequence_sha256': p.get('expanded_sequence_sha256'),
            'independent_score': evaluations[0] if evaluations else None,
            'stop_reason': p.get('error') or result.get('error') or ('independent_evaluation_FAIL' if status=='TASK_FAIL' else None),
            'hardware_calls': result.get('hardware_calls'), 'versions': result.get('versions'),
            'decision_wait_mode': p.get('decision_wait_mode'), 'faults': [e for e in events if e['kind'] in ('FAULT','FINAL_OBSERVATION_FAILED')]}


def report(root, ledger):
    (root/'ledger.json').write_text(json.dumps(ledger, indent=2, ensure_ascii=False)+'\n')
    rows = []
    for r in ledger['episodes']:
        u = r.get('usage', {}).get('sum_of_observed_same_fields', {})
        lat = [round(x['policy_latency_s'], 6) if x['policy_latency_s'] is not None else None for x in r.get('requests', [])]
        fmt = lambda x: '—' if x is None else '%.6f' % x
        score = r.get('independent_score')
        score_text = '%s; xy=%.6f mm' % (score['status'], score['xy_error_m']*1000) if score else 'NOT_RUN'
        rows.append('| %s | %d | %s | %s | %s | `%s` | %s / %s | %s | %s / `%s` | %s | %s |' % (
            r['condition'], r['seed'], r['status'], r.get('actual_requests','—'), lat, json.dumps(u,ensure_ascii=False),
            fmt(r.get('placement_wall_s')),fmt(r.get('placement_physics_s')),fmt(r.get('initialization_wall_s')),
            ' → '.join(x['name'] for x in r.get('primitive_sequence',[])) or '[]', r.get('executed_sequence_sha256','—'),
            score_text, r.get('stop_reason') or '—'))
    text = '# '+SCOPE+'\n\n'
    text += '四个预先固定的新回合；历史通道验收不纳入。每回合新进程、同一固定布局，seed 不代表不同布局，不称精确状态克隆。视频统一关闭。\n\n'
    text += '| condition | seed | 状态 | 实际请求数 | 各请求LocalPolicy延迟 s | usage各原字段分别累计 | 放置墙钟/物理 s | 初始化墙钟 s | 实际原语序列 / SHA256 | 独立评分 | 停止原因 |\n'
    text += '|---|---:|---|---:|---|---|---|---:|---|---|---|\n'+'\n'.join(rows)+'\n\n'
    text += 'usage 仅跨请求累加同名字段，不将 cached/reasoning 等可能子项再加入 input/output；原始每请求 usage 和缺失标记保存在 ledger.json。\n\n'
    text += '初始化墙钟来自既有场景 INITIALIZING 到首次放置 OBSERVE_ENTER 的时间戳，包含场景构建和持物设置，不含预检/导入；放置时间沿用原入口汇总。nonplacement_wall_s 另含初始化外围开销和收尾，不冒称纯初始化。\n\n'
    text += 'physics_paused；每回合放置总预算120秒；原 LocalPolicy 将单请求 timeout 限制为剩余预算。初始化抓取不计模型成果。共享 ENGINEERING_ORACLE 辅助保持不变。\n\n'
    text += '服务端身份、effort、内部重试没有明确回执时为 unknown；客户端仍请求 gpt-6-astra/medium。合法stop/评分FAIL纳入；接口/协议/检查/执行异常终止后续批次。\n\n'
    text += '不是正式E1非劣结果，不外推泛化成功率，不自动展开E2/E3/E4。\n'
    (root/'REPORT.md').write_text(text)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--codex-executable',type=Path,required=True);p.add_argument('--authorize-model',action='store_true')
    p.add_argument('--max-model-requests',type=int,required=True)
    a=p.parse_args()
    if not a.authorize_model or a.max_model_requests != 10:p.error('requires explicit --authorize-model --max-model-requests 10')
    root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    runner=Path(__file__).with_name('run_sim_placement.py').resolve()
    frozen={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in
            [runner,a.codex_executable.resolve(),*list(runner.parents[1].joinpath('sim_skills').glob('*.py')),
             runner.parents[1]/'scripts/codex_astra_mac_bridge.py',runner.parents[1]/'config/sim_rm65_targets.json',
             runner.parents[1]/'decision_backends.py',runner.parents[1]/'io_utils.py',runner.parents[1]/'bimanual_demo/primitives.py']}
    ledger={'scope':SCOPE,'authorized_cap':10,'allocated_caps':0,'video':False,'budget_s_per_placement':120,
            'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'protected_sha256':{str(k):v for k,v in frozen.items()},
            'episodes':[{'seed':seed,'condition':c,'cap':cap,'name':'%02d-seed%d-%s'%(i+1,seed,c),'status':'PENDING'} for i,(seed,c,cap) in enumerate(SPECS)]}
    process=None;cancelled=False;abort_reason=None
    def stop(*_):
        nonlocal cancelled
        cancelled=True
        if process is not None and process.poll() is None:process.terminate()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    report(root,ledger)
    for row in ledger['episodes']:
        if cancelled or abort_reason:
            row.update(status='NOT_RUN',actual_requests=0,stop_reason=abort_reason or 'BATCH_CANCELLED');continue
        if any(hashlib.sha256(path.read_bytes()).hexdigest()!=sha for path,sha in frozen.items()):
            abort_reason='FROZEN_FILE_CHANGED';row.update(status='NOT_RUN',actual_requests=0,stop_reason=abort_reason);continue
        ledger['allocated_caps']+=row['cap']
        assert ledger['allocated_caps']<=10
        output=root/row['name']
        cmd=[sys.executable,str(runner),'--assets',str(a.assets.resolve()),'--output',str(output),
             '--seed',str(row['seed']),'--condition',row['condition'],'--model','local-cli','--authorize-model',
             '--max-model-requests',str(row['cap']),'--codex-executable',str(a.codex_executable.absolute()),'--budget-s','120']
        row.update(status='RUNNING',command=cmd,output=str(output));report(root,ledger)
        print(json.dumps({'event':'EPISODE_START','episode':row['name'],'cap':row['cap']}),flush=True)
        started=time.monotonic()
        try:
            with (root/(row['name']+'.stdout.log')).open('x') as out,(root/(row['name']+'.stderr.log')).open('x') as err:
                process=subprocess.Popen(cmd,stdout=out,stderr=err)
                row['pid']=process.pid
                try:code=process.wait(timeout=240)
                except subprocess.TimeoutExpired:
                    row['outer_timeout']=True;process.terminate()
                    try:code=process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();code=process.wait()
            row.update(summarize(output,code),return_code=code)
            if row.get('actual_requests') is None or row['actual_requests']>row['cap'] or row.get('outer_timeout'):
                row.update(status='ABORT_ACCOUNTING_OR_TIMEOUT',abort_batch=True)
            previous=[x['versions'] for x in ledger['episodes'] if x is not row and x.get('versions')]
            if previous and row.get('versions')!=previous[0]:row.update(status='ABORT_VERSION_DRIFT',abort_batch=True)
            if row['abort_batch']:abort_reason=row.get('stop_reason') or row['status']
        except Exception as exc:
            abort_reason=repr(exc);row.update(status='ABORT_LEDGER_OR_PROCESS',abort_batch=True,stop_reason=abort_reason)
            raw_result=read(output/'result.json', {})
            row['actual_requests']=raw_result.get('model_calls')
            row['worker_command_records']=len(list(output.glob('model-worker/*/command.json')))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            row['outer_wall_s']=time.monotonic()-started
        report(root,ledger)
        print(json.dumps({'event':'EPISODE_END','episode':row['name'],'status':row['status'],'requests':row.get('actual_requests'),'reason':row.get('stop_reason')}),flush=True)
    ledger.update(abort_reason=abort_reason,cancelled=cancelled,finished=True,
                  actual_requests_observed=sum(x.get('actual_requests') or 0 for x in ledger['episodes']))
    report(root,ledger)
    return 1 if abort_reason or cancelled else 0


if __name__=='__main__':raise SystemExit(main())
