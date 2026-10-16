import argparse,json,traceback
from pathlib import Path
from dual_scene import DualScene,LAYOUT
from initial_v1 import prepare_left,expert_move
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();w=None;r={'status':'RUNNING','model_calls':0}
try:
 w=DualScene(a.output);w.start_video();prepare_left(w)
 expert_move(w,'left',[.36,.20,.102],[0,1,0,0])
 obj=w.cube.get_pose().p.tolist();obj[1]-=.01369781;q=[-.5,.5,.5,.5]
 expert_move(w,'right',[obj[0],obj[1]-.07,obj[2]],q);expert_move(w,'right',obj,q)
 w.phase_name='right_close';w.arms['right'].gripper(.45);w.tick(150)
 w.phase_name='left_release';w.arms['left'].gripper(1)
 w.phase_name='right_independent_hold';w.tick(1250)
 if not w.arms['right'].bilateral_pad_contact():raise RuntimeError('RIGHT_NOT_HOLDING')
 w.observe(w.output/'held');r['status']='PASS_HOLD_ONLY'
except BaseException as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:
 if w:r.update(steps=w.steps);w.close()
 Path(a.output,'result.json').write_text(json.dumps(r,indent=2));print(r,flush=True)
