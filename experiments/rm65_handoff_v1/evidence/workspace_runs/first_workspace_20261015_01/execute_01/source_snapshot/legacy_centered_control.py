import argparse,json,time,traceback
from pathlib import Path
from dual_scene import DualScene,RM65Scene
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--smoke-only',action='store_true');p.add_argument('--handoff-only',action='store_true');p.add_argument('--hold-only',action='store_true');a=p.parse_args();w=None;result={'status':'RUNNING','model_calls':0,'hardware_connections':0}
try:
 w=DualScene(a.output);w.start_video();w.observe(w.output/'initial_observation');result['shared_scene_articulations']=len(w.scene.get_all_articulations())
 def move(side,xyz,q=[0,1,0,0]):
  r=RM65Scene.move_tcp(w.arms[side],[*xyz,*q])
  if not r['ok']:raise RuntimeError('BASELINE_'+side+':'+str(r))
 if not a.smoke_only:
  left=w.arms['left'];right=w.arms['right']
  from legacy_initial import prepare_left
  prepare_left(w)
  if not a.handoff_only:
   # Right approaches the other pair of cube faces sideways; private script only.
   obj=w.cube.get_pose().p.tolist();q=[-.5,.5,.5,.5];obj[1]-=.0135 # measured pad-center advance during closure; private geometric control
   move('right',[obj[0],obj[1]-.06,obj[2]],q);move('right',obj,q);w.phase_name='right_close';right.gripper(.45);w.tick(150)
   if not any(r['bilateral_contact']['right'] for r in w.records[-500:]):raise RuntimeError('RIGHT_NO_CONTACT_ESTABLISHED')
   w.phase_name='left_release';left.gripper(1.);w.phase_name='right_independent_hold';w.tick(1250)
   if not right.bilateral_pad_contact():raise RuntimeError('RIGHT_NOT_HOLDING')
   if not a.hold_only:
    move('right',[.60,.16,.12],q);move('right',[.60,.16,.04],q);w.phase_name='right_release';right.gripper(1.);w.tick(300)
    w.observe(w.output/'final_observation')
    # Keep the original single-arm terminal evaluator, explicitly using the new target.
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'astra_realman_harness'))
    from sim_skills.rm65 import RM65Backend
    right.cfg['scene']['place_zone_xy']=w.target_xy
    backend=RM65Backend.__new__(RM65Backend);backend.s=right
    result['original_terminal_evaluator_new_target']=backend.evaluate()
    result['placed']=result['original_terminal_evaluator_new_target']['status']=='PASS'
    if not result['placed']:raise RuntimeError('PLACE_NOT_STABLE')
 result['status']='PASS';result['scope']='shared_scene_smoke' if a.smoke_only else ('left_held_initialization_only' if a.handoff_only else ('right_hold_only' if a.hold_only else 'full_handoff'))
except BaseException as e:result.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:
 if w:result.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt);w.close()
 a.output.mkdir(parents=True,exist_ok=True);(a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
