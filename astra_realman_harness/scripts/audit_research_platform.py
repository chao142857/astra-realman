#!/usr/bin/env python3
"""Read existing platform artifacts; no scene, model, or hardware launch."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_v1.client import Replay

def audit(run):
    run=Path(run);result=json.loads((run/'result.json').read_text());replay=Replay(run/'public')
    rows=list(replay.events());observations=[e['data'] for e in rows if e['kind']=='observation']
    for o in observations:
        for camera in ('assembly','fixed','wrist'):replay.rgb(o,camera)
    assert all(a['monotonic']<=b['monotonic'] for a,b in zip(rows,rows[1:]))
    workers=[]
    for folder in sorted((run/'private/workers').glob('request-*')):
        w=json.loads((folder/'input_only/wire.json').read_text());payload=json.loads((folder/'input_payload.json').read_text())
        # Reconstruct the actual inference payload through the unchanged projector.
        from sim_skills.full_pnp.wire import existing_infer_payload
        assert payload==existing_infer_payload(folder/'input_only')
        state=w['observation']['state']
        from sim_skills.model import state_projection
        assert state==state_projection(state)
        assert w['history']['completed_transitions']==[] and w['history']['visual_hypotheses']==[]
        assert w['evidence_packet'] is None and w['evidence_reuse'] is None
        for a in w['attachments']:
            assert hashlib.sha256((folder/'input_only'/a['file']).read_bytes()).hexdigest()==a['sha256']
        bridge=list((folder/'infer_output/bridge').glob('*'));record=None;raw=None;parsed=None
        if bridge:
            assert len(bridge)==1
            assert json.loads((bridge[0]/'prompt.json').read_text())==payload['context']
        if (folder/'worker.json').is_file() and (folder/'worker.json').stat().st_size:
            try:record=json.loads((folder/'worker.json').read_text())
            except ValueError:pass
        if record:raw=record.get('raw')
        if (folder/'parsed.json').is_file():
            parsed=json.loads((folder/'parsed.json').read_text());assert parsed==json.loads(raw)
        workers.append({'request':folder.name,'attempt':json.loads((folder/'attempt.json').read_text()),
            'raw_parsed_equal':parsed is not None,'bridge_prompt_matches_final_payload':bool(bridge),
            'usage_raw':record.get('usage') if record else None,'server_model':record.get('server_model','unknown') if record else 'unknown',
            'server_effort':record.get('server_effort','unknown') if record else 'unknown',
            'attachments':w['attachments'],'wire_sha256':hashlib.sha256((folder/'input_only/wire.json').read_bytes()).hexdigest()})
    begin={e['data']['chunk_id']:e for e in rows if e['kind']=='action_begin'}
    timeline=[]
    for e in rows:
        if e['kind']=='execution':
            d=e['data'];b=begin[d['chunk_id']]
            timeline.append({'chunk':d['chunk_id'],'actions':d['actions'],'ok':d['ok'],
             'start_step':b['physics_step'],'end_step':e['physics_step'],
             'wall_s':e['monotonic']-b['monotonic'],'physics_s':(e['physics_step']-b['physics_step'])*.004,
             'unexecuted_count':d['unexecuted_count'],'error_code':d['error_code']})
    return {'audit_status':'PASS','source':result['source'],'artifact_hashes_verified':True,
      'observations':len(observations),'image_hash_checks':len(observations)*3,'public_events':len(rows),
      'time_order':'MONOTONIC','workers':workers,'timeline':timeline,'run_status':result['status'],
      'real_model_calls':result['real_model_calls'],'hardware_calls':result['hardware_calls'],
      'private_score_access':'OWNER_ONLY; this audit does not read private score',
      'limitations':'wire audit checks current fixed compatibility projection; fake raw does not prove real visual decisions'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=audit(a.run)
    with a.output.open('x') as f:json.dump(out,f,indent=2);f.write('\n')
    print(json.dumps({k:out[k] for k in ('audit_status','observations','image_hash_checks','real_model_calls','hardware_calls')}))
