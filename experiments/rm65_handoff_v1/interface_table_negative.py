"""One predeclared empty-table closure control, not a repaired Astra answer.

D1's grasp path is translated +0.12m in world Y to remove cube contact from
closure. The original .027m endpoint/.15 request and orientation are retained.
Used only to test that contact-dependent control still stops table collisions.
Never imported by an online run; no model, new scene, or parameter search.
"""
import argparse,hashlib,json,os,traceback
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--physics-only',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parent;os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    if a.physics_only:
        from replay_without_rendering import install
        install()
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from numeric_action_chunk import execute_chunk
    from right_hold_velocity_v3 import install
    if a.physics_only:
        from replay_without_rendering import omit_observations
        omit_observations(DualScene)
    path=root/'evidence/full_task_real_20261016/episode/decision_000/raw.txt'
    raw=path.read_bytes();value=json.loads(raw)
    for stage in value['stages']:
        for action in stage['actions']:
            for pose in action.get('waypoints_world_wxyz',[]):pose[1]+=.12
    report={'source':'PRIVATE_PREDECLARED_NEGATIVE_CONTROL_NOT_ASTRA_RESULT',
        'original_raw_sha256':hashlib.sha256(raw).hexdigest(),'control_change':'TCP world Y +0.12m; all other request fields unchanged',
        'real_model_requests':0,'bridge_connections':0,'status':'RUNNING',
        'rendering':'OMITTED_NO_RGB_OR_VIDEO' if a.physics_only else 'ORIGINAL_FOUR_CAMERAS'}
    relocate_runtime_mesh_paths(CONFIG);w=None
    try:
        w=DualScene(a.output);install(w);w.start_video();w.observe(w.output/'initial')
        report['receipt']=execute_chunk(w,value);report['status']='FAIL_NO_TABLE_STOP'
    except Exception as exc:
        report.update(error=repr(exc),traceback=traceback.format_exc(),status='STOP_REQUIRES_PAIR_AUDIT')
        if w:
            for path in w.output.glob('group_*/contact_guard_summary_PRIVATE.json'):
                guard=json.loads(path.read_text());danger=guard.get('first_danger')
                if danger and any('table' in str(pair) and 'Support_Link' in str(pair) for pair in danger['forbidden_fcl_pairs']):
                    report.update(status='PASS_TABLE_COLLISION_STOP',first_table_danger=danger,
                        first_bilateral_step=guard['first_bilateral_step'])
    finally:
        if w:
            report['physics_steps']=w.steps;w.observe(w.output/'final');w.close()
            (w.output/'negative_control.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('receipt','first_table_danger')},indent=2))


if __name__=='__main__':main()
