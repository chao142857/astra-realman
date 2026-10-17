"""Finite offline replay of archived Astra answers; never invokes Bridge inference."""
import argparse,ast,copy,gzip,hashlib,importlib.util,json,os,textwrap,traceback,types
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',choices=['legacy_d1','contact_d1','sequential_d4'],required=True)
    p.add_argument('--contact-closure-time-scale',type=int,choices=[1,2],default=1)
    p.add_argument('--left-contact-hold',choices=['original','native_damping0_v4'],default='original')
    p.add_argument('--physics-only',action='store_true',help='Real PhysX without RGB/video; archived exact-state checks still required')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent;os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    if a.physics_only:
        from replay_without_rendering import install as omit_rendering
        omit_rendering()
    import dual_scene
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from numeric_action_chunk import execute_chunk
    from right_hold_velocity_v3 import install
    if a.physics_only:
        from replay_without_rendering import omit_observations
        omit_observations(DualScene)
    archived=root/'evidence/full_task_real_20261016/episode'
    snapshot=archived/'source_snapshot'
    spec=importlib.util.spec_from_file_location('_archived_chunk_replay',snapshot/'numeric_action_chunk.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    source=(snapshot/'dual_scene.py').read_text();tree=ast.parse(source)
    node=next(f for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='DualScene' for f in c.body if isinstance(f,ast.FunctionDef) and f.name=='execute_group')
    env=vars(dual_scene).copy();exec(compile(textwrap.dedent(ast.get_source_segment(source,node)),'<archived_624d80f_execute_group>','exec'),env)
    legacy_group=env['execute_group']
    relocate_runtime_mesh_paths(CONFIG);w=None
    report={'case':a.case,'real_requests':0,'bridge_connections':0,'source':'ARCHIVED_ASTRA_OFFLINE_REPLAY',
        'contact_closure_time_scale':a.contact_closure_time_scale,'left_contact_hold':a.left_contact_hold,'altered_model_targets':False,'object_binding':False,'status':'RUNNING','source_answers':[],
        'rendering':'OMITTED_NO_RGB_OR_VIDEO' if a.physics_only else 'ORIGINAL_FOUR_CAMERAS'}
    def proposal(i):
        path=archived/f'decision_{i:03d}/raw.txt';raw=path.read_text();report['source_answers'].append({'decision':i+1,'sha256':hashlib.sha256(raw.encode()).hexdigest()});return json.loads(raw)
    try:
        w=DualScene(a.output);install(w)
        w.contact_closure_time_scale=a.contact_closure_time_scale
        from contact_servo_readback import install as readback
        readback(w)
        if a.left_contact_hold=='native_damping0_v4':
            from left_contact_hold_v4 import install as left_hold
            report['left_control_variant']=left_hold(w)
        w.start_video();w.observe(w.output/'initial')
        current=w.execute_group
        if a.case in ('legacy_d1','sequential_d4'):
            w.execute_group=types.MethodType(legacy_group,w)
            for i in range(3 if a.case=='sequential_d4' else 1):
                r=legacy.execute_chunk(w,proposal(i));report.setdefault('legacy_receipts',[]).append(r)
                if i==0:assert not r['ok'] and 'INTERPOLATED_COLLISION:left:105:' in r['reason'],r
                else:assert r['ok'],r
                if a.case=='sequential_d4' and i<2:w.observe(w.output/f'prefix_observation_{i+1}')
            target_step=27325 if a.case=='sequential_d4' else 11675
            original=[json.loads(x) for x in gzip.decompress((archived/'physics.jsonl.gz').read_bytes()).splitlines()]
            expected=next(x for x in original if x['step']==target_step);actual=w.records[-1]
            checks={key:actual[key]==expected[key] for key in ('step','object_pose','object_velocity','drive_targets','bilateral_contact')}
            checks.update({s+'_qpos':actual['arms'][s]['qpos']==expected['arms'][s]['qpos'] for s in ('left','right')})
            report['archived_start_state_exact_checks']=checks;assert all(checks.values()),checks
            w.observe(w.output/'matched_archived_state')
            w.execute_group=current
            if a.case=='legacy_d1':report['status']='REPRODUCED_ORIGINAL_PRECHECK_REJECTION';return
        value=proposal(0 if a.case=='contact_d1' else 3)
        before=w.steps;report['new_execution_start_step']=before
        r=execute_chunk(w,value);report['new_receipt']=r
        report['status']='COMPLETED_NUMERIC_REPLAY' if r['ok'] else 'REJECTED_OR_PARTIAL_REPLAY'
        report['new_execution_end_step']=w.steps
    except Exception as exc:
        report.update(status='PHYSICAL_OR_EXECUTION_STOP',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt)
            w.observe(w.output/'final');w.close();(w.output/'replay.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('legacy_receipts','new_receipt')},indent=2))


if __name__=='__main__':main()
