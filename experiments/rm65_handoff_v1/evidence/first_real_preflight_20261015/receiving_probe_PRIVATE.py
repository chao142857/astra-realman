"""Two declared endpoint queries only; not a transfer witness or model input."""
import argparse,json,os,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
D=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(D));os.environ['RM65_LAYOUT']=str(D/'scene_v4_ready_transfer_1100.json')
from dual_scene import DualScene
from initial_transfer import prepare_left
w=DualScene(a.output);rows=[]
try:
    prepare_left(w);before=w.steps
    for xyz in ([.36,0,.25],[.36,0,.30]):
        goal=[*xyz,2**-.5,0,-2**-.5,0]
        row={'arm':'right','tcp_world_wxyz':goal,'executed':False}
        try:
            plan=w.arms['right'].plan_tcp(goal)
            row.update(status='ENDPOINT_IK_AND_COLLISION_PASS_ONLY',arm_q=plan['position'][-1].tolist())
        except (ValueError,RuntimeError) as exc:row.update(status='REJECTED',reason=str(exc))
        rows.append(row);print(json.dumps(row),flush=True)
    assert w.steps==before
    result={'queries':rows,'probe_motion_steps':0,'model_requests':0,
            'limitation':'No simultaneous dual-arm path, receiving contact, or physical transfer established; endpoint refusals do not identify model failure.'}
    (w.output/'probe_PRIVATE.json').write_text(json.dumps(result,indent=2)+'\n')
finally:w.close()
