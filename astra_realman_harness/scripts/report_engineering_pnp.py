#!/usr/bin/env python3
"""Independent closed-archive grasp/transport/release/exit acceptance; no execution."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_engineering_pnp import classify

def read(p):return json.loads(p.read_text())
def lines(p):return [json.loads(s) for s in p.read_text().splitlines()]
def completed_stage(ends,index):
    return len(ends)>index and ends[index]['data']['result']['ok'] is True

def release_exit_checks(score,ends):
    # Initial open/clear state is not evidence a release/exit action occurred.
    return {'release':score.get('released') is True and completed_stage(ends,5),
            'exit':score.get('exited') is True and completed_stage(ends,6)}

def evaluate(run):
    run=Path(run);r=read(run/'result.json');e=r.get('episode',{});score=e.get('score') or {}
    timeline=lines(run/'episode/timeline.jsonl') if (run/'episode/timeline.jsonl').exists() else []
    trace=lines(run/'scene/private_scoring_trace.jsonl') if (run/'scene/private_scoring_trace.jsonl').exists() else []
    begins=[x for x in timeline if x['kind']=='CHUNK_BEGIN'];ends=[x for x in timeline if x['kind']=='CHUNK_END']
    initial=read(run/'scene/initial_object_private.json');cfg=read(run/'scene/assembly_config.json')
    transport=[x for x in trace if len(begins)>3 and len(ends)>3 and begins[3]['physics_step']<x['step']<=ends[3]['physics_step']]
    distance=None;slip=None;minlift=None;allcontacts=None
    if transport:
        distance=float(np.linalg.norm(np.array(transport[-1]['object_pose'][:2])-transport[0]['object_pose'][:2]))
        relative=np.array([np.array(x['object_pose'][:3])-x['grasp_center'] for x in transport])
        slip=float(np.linalg.norm(relative-relative[0],axis=1).max());minlift=min(x['object_pose'][2]-initial[2] for x in transport)
        allcontacts=all(x['closed'] and x['bilateral_contact'] for x in transport)
    checks={'grasp_and_lift':score.get('grasp_execution_assessment',{}).get('status')=='STABLE_HOLD_VERIFIED',
       'transport':bool(transport and distance>=.05 and slip<=.03 and minlift>=.05 and allcontacts),
       **release_exit_checks(score,ends),
       'stable_placement':score.get('stable_in_target') is True,'native_full_task_score':score.get('strict_success') is True,
       'all_7_script_chunks_completed':e.get('completed_chunks')==7,'no_safety_abort':score.get('safety_abort') is False}
    contacts=lines(run/'scene/grasp_execution_private.jsonl')
    close=[x for x in contacts if x['event'] in ('CLOSING_END','CLOSING_ABORT')]
    firstcontact=next((x['step'] for x in trace if x['bilateral_contact']),None)
    video=run/'scene/execution.mp4';vinfo=None
    if video.exists():
        import imageio.v2 as imageio
        reader=imageio.get_reader(video);count=0
        for frame in reader:count+=1
        meta=reader.get_meta_data();reader.close();index=lines(run/'scene/video_frames.jsonl')
        steps=[x.get('step',x.get('sim_step')) for x in index]
        if any(x is None for x in steps):raise ValueError('VIDEO_INDEX_SCHEMA')
        vinfo={'file':'scene/execution.mp4','sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
          'decoded_frames':count,'indexed_frames':len(index),'first_step':steps[0],'last_step':steps[-1],
          'step_stride_25':all(b-a==25 for a,b in zip(steps,steps[1:])),
          'fps':meta.get('fps'),'complete_decoding':count==len(index),
          'semantics':'native untrimmed fixed+wrist two-view composite sampled every25 physics steps (0.1s); not wall-time video; initialization before step100 not rendered'}
    return {'case':run.name,'source':'ENGINEERING_REFERENCE','original_status':r['status'],
       'independent_full_task_status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,
       'failure_class':classify(r),'failure_raw':e.get('error') or r.get('error'),
       'configured_object_initial_xyz':cfg['scene']['cube_initial_xyz'],'actual_settled_object_pose':initial,
       'target_xy':cfg['scene']['place_zone_xy'],'coordinate_source':'predeclared layout config + measured private simulator initial pose; not model input',
       'transport':{'object_xy_displacement_m':distance,'max_relative_slip_m':slip,'min_lift_m':minlift,'all_closed_bilateral':allcontacts},
       'closure':close[-1] if close else None,'first_bilateral_step':firstcontact,
       'placement_error_m':score.get('placement_xy_error_m'),'max_lift_m':score.get('max_lift_m'),
       'minimum_object_contact_separation_m':score.get('minimum_physx_object_contact_separation_m'),
       'drop_while_closed':score.get('dropped_while_closed'),'safety_abort':score.get('safety_abort'),
       'initialization_wall_s':r.get('initialization_wall_s'),'initialization_physics_s':r.get('initialization_physics_s'),
       'execution_wall_s':e.get('wall_s'),'execution_physics_s':e.get('physics_s'),'process_wall_s':r.get('process_wall_s'),
       'completed_chunks':e.get('completed_chunks'),'actual_actions':score.get('executed_actions'),'grasp_attempts':score.get('grasp_attempts'),
       'video':vinfo,'model_calls':r['real_model_calls'],'hardware_calls':r['hardware_calls']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True);p.add_argument('--batch',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    runs=[a.reference,*sorted(a.batch.glob('L*-r*'))];result=[evaluate(x) for x in runs if x.is_dir()]
    with a.output.open('x') as f:json.dump({'scope':'ENGINEERING_REFERENCE_NOT_ASTRA_OR_BF','cases':result,'physical_runs':len(result),'model_calls':0,'hardware_calls':0},f,indent=2)
    print(json.dumps([{k:x[k] for k in ('case','original_status','independent_full_task_status','failure_class')} for x in result]))
if __name__=='__main__':main()
