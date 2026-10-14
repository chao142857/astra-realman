"""Independent deterministic SAPIEN validation design; not visible to estimators."""
import argparse,copy,hashlib,json,math,subprocess,sys
from pathlib import Path
from spatial_eval.data import box,task
from pilot02_specs import yaw,answer
from spatial_eval.schema import write
I=[1.,0.,0.,0.]
def designs():
 result=[]
 for index,(sign,offset,arch) in enumerate([(-1,-.018,False),(1,.022,False),(-1,.011,True)]):
  start=[.155,offset,.11];goal=[.745,offset,.11];side=sign*.215
  objects=[box('target',start,[.052,.052,.052])];regions=[box('task_volume',goal,[.105,.12,.11]),box('workspace',[.46,0,.15],[.76,.60,.26])]
  obstacles=[box('barrier',[.465,-sign*.075,.145],[.055,.40,.25]),box('suspended_beam',[.49,side,.205],[.15,.034,.026])]
  if arch:
   obstacles[1]=box('suspended_beam',[.465,side,.205],[.032,.23,.026])
   obstacles.extend([box('post_inner',[.465,side-sign*.104,.105],[.032,.022,.21]),box('post_outer',[.465,side+sign*.104,.105],[.032,.022,.21])])
  witnesses=answer(goal,points=[[start[0],side,.11],[goal[0],side,.11],goal]);alt=answer(goal,points=[[start[0],side+sign*.006,.12],[goal[0],side+sign*.006,.12],goal])
  negatives={'straight':answer(goal,points=[goal]),'too_high':answer(goal,points=[[start[0],side,.35],[goal[0],side,.35],goal]),'hit_suspended_beam':answer(goal,points=[[start[0],side,.205],[goal[0],side,.205],goal])}
  result.append({'scene_id':f'v2_val_path_{index+1:02d}','family':'independent_bounded_path','objects':objects,'obstacles':obstacles,'regions':regions,'kind':'path','orientation_policy':{'mode':'fixed','quaternion_wxyz':I,'tolerance_rad':.02},'witness':witnesses,'alternate_witnesses':[alt],'negative_controls':negatives})
 for index,(angle,gap,center) in enumerate([(17,.0035,[.605,-.045,.115]),(73,.006,[.655,.065,.125]),(137,.010,[.625,-.005,.12])]):
  target=box('target',[.145,-.345,.085],[.125,.043,.061],yaw(17));inner=[.125+2*.009,.043+2*gap];outer=[.43,.45];obstacles=[]
  for name,c,size in [('xm',[-(outer[0]+inner[0])/4,0,0],[(outer[0]-inner[0])/2,outer[1],.19]),('xp',[(outer[0]+inner[0])/4,0,0],[(outer[0]-inner[0])/2,outer[1],.19]),('ym',[0,-(outer[1]+inner[1])/4,0],[inner[0],(outer[1]-inner[1])/2,.19]),('yp',[0,(outer[1]+inner[1])/4,0],[inner[0],(outer[1]-inner[1])/2,.19])]:
   a=math.radians(angle);position=[center[0]+c[0]*math.cos(a)-c[1]*math.sin(a),center[1]+c[0]*math.sin(a)+c[1]*math.cos(a),center[2]];obstacles.append(box('block_'+name,position,size,yaw(angle)))
  result.append({'scene_id':f'v2_val_yaw_{index+1:02d}','family':'independent_free_yaw','objects':[target],'regions':[box('task_volume',center,[.29,.29,.16])],'obstacles':obstacles,'kind':'placement','orientation_policy':{'mode':'upright_free_yaw','local_axis':[0,0,1],'world_axis':[0,0,1],'max_tilt_rad':.02},'witness':answer(center,yaw(angle)),'alternate_witnesses':[answer(center,yaw(angle+.5)),answer([center[0]+.0002,center[1],center[2]],yaw(angle))],'negative_controls':{'wrong_yaw':answer(center,yaw(angle+90)),'in_solid':answer(obstacles[0]['center_m'],yaw(angle)),'not_upright':answer(center,[0,1,0,0])}})
 for s in result:
  s['obstacles'].append(box('table',[.48,0,-.025],[1.6,1.5,.04]));c={'object_id':'target','allowed_region_id':'task_volume','clearance_m':.002,'required_quaternion_wxyz':s['orientation_policy'].get('quaternion_wxyz'),'orientation_tolerance_rad':.02}
  if s['kind']=='path':c.update(start_position_m=s['objects'][0]['center_m'],workspace_region_id='workspace')
  public='; '.join(f"{r['id']}: center={r['center_m']} m, full_size={r['size_m']} m, wxyz={r['quaternion_wxyz']}" for r in s['regions'])
  instruction='The red cuboid is target; gray solids are obstacles. Green wireframes mark public task volumes, not solids. Choose any collision-free object-center placement fully inside task_volume with the specified SAT-axis clearance. All positions use robot_base=simulation world, meters; +z up. Static geometry only; no support, robot or dynamics requirement. Public volumes: '+public+'. '
  instruction+=('Move at fixed orientation through workspace using center waypoints. The entire object must remain in the public workspace.' if s['kind']=='path' else 'Return no waypoints. Keep local +z upright within 0.02 radians; choose yaw freely. No target quaternion is prescribed.')
  s['task']=task(s['kind'],'plan',constraints=c,instruction=instruction)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--single');a=p.parse_args()
 if a.single:
  from pilot02_render import capture
  capture(next(s for s in designs() if s['scene_id']==a.single),a.output)
 else:
  a.output.mkdir(parents=True,exist_ok=False);write(a.output/'design_before_render.json',{'designs':designs(),'selection':'six deterministic new validation scenes; all retained; estimator locked beforehand; no score-based selection','old_four_scenes':'development only, v2 informed by their GT diagnosis','new_model_calls':0,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
  for s in designs():
   print('Rendering',s['scene_id'],flush=True);subprocess.run([sys.executable,__file__,'--single',s['scene_id'],'--output',str(a.output/s['scene_id'])],check=True)
  write(a.output/'freeze.json',{'files':[{'file':str(p.relative_to(a.output)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(a.output.rglob('*')) if p.is_file()],'new_astra_requests':0})
