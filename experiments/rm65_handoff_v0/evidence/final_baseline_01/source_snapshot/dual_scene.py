"""Two original RM65 articulations in ONE SAPIEN/PhysX scene. No hardware imports."""
import os,sys,copy,json,time,math,hashlib,threading,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
ASSETS=Path(os.environ['RM65_ASSETS']).resolve()
manifest=json.loads((ASSETS/'asset_manifest.json').read_text())
for rel,record in manifest['files'].items():
 if hashlib.sha256((ASSETS/rel).read_bytes()).hexdigest()!=record['sha256']:raise ValueError('ASSET_HASH_MISMATCH:'+rel)
sys.path.insert(0,str(ASSETS/'scripts'))
from rm65_scene import RM65Scene,camera_pose,CONFIG
from run_expert import write_json

class Arm(RM65Scene):
 def init_planner(self):
  from mplib.sapien_utils import SapienPlanner,SapienPlanningWorld
  from mplib.sapien_utils.conversion import convert_object_name
  self.motion=SapienPlanner(SapienPlanningWorld(self.scene,[self.robot]),self.prefix+'Link6',joint_vel_limits=[.5]*6,joint_acc_limits=[1.]*6)
  for a,b in map(tuple,self.ignore):self.motion.acm.set_entry(self.prefix+a,self.prefix+b,True)
  for arm in self.world.arms.values():
   for a,b in map(tuple,arm.ignore):self.motion.acm.set_entry(arm.prefix+a,arm.prefix+b,True)
   self.motion.acm.set_entry(arm.prefix+'base_link',convert_object_name(arm.stand),True)
   for pad in arm.pad_vertices:self.motion.acm.set_entry(arm.prefix+pad,convert_object_name(self.cube),True)
 def bilateral_pad_contact(self):
  touching=set()
  for c in self.scene.get_contacts():
   names=[b.entity.name for b in c.bodies]
   if 'target_cube' not in names:continue
   for n in names:
    if n in [self.prefix+p for p in self.pad_vertices] and any(p.separation<=.0002 and np.linalg.norm(p.impulse)>1e-6 for p in c.points):touching.add(n)
  return len(touching)==2
 def tick(self,n):return self.world.tick(n)
 def monitor(self):
  q=self.robot.get_qpos();lim=self.robot.get_qlimits();tol=self.cfg['control']['joint_limit_tolerance_rad']
  if not np.isfinite(q).all() or np.any(q<lim[:,0]-tol) or np.any(q>lim[:,1]+tol):raise RuntimeError(self.prefix+'ACTUAL_JOINT_LIMIT')
  if np.max(np.abs(q[self.arm_indices]-self.arm_target))>self.cfg['control']['max_tracking_error_rad']:raise RuntimeError(self.prefix+'TRACKING_ERROR')
 def plan_tcp(self,pose):
  """Fixed closest IK + smooth joint interpolation. No OMPL rerouting or target edits."""
  import mplib
  p=np.asarray(pose,float)
  if p.shape!=(7,) or not np.isfinite(p).all() or abs(np.linalg.norm(p[3:])-1)>.001:raise ValueError('INVALID_POSE')
  if not (-.15<=p[0]<=.9 and -.4<=p[1]<=.4 and .025<=p[2]<=.5):raise ValueError('TCP_WORKSPACE')
  if self.motion is None:self.init_planner()
  q=self.robot.get_qpos();flange=self.links['Link6'].get_pose().to_transformation_matrix();local=flange[:3,:3].T@(self.pads().mean(0)-flange[:3,3]);fp=p.copy();fp[:3]-=Rotation.from_quat(np.roll(p[3:],-1)).as_matrix()@local
  self.motion.update_from_simulation();goal=self.motion._transform_goal_to_wrt_base(mplib.Pose(fp[:3],fp[3:]));mask=np.ones(len(q),dtype=bool);mask[self.arm_indices]=False
  status,ik=self.motion.IK(goal,q,mask=mask,return_closest=True)
  self.log('numeric_ik',{'target_tcp':p.tolist(),'target_flange':fp.tolist(),'status':status,'start_qpos':q.tolist(),'goal_qpos':None if ik is None else ik.tolist(),'no_target_correction':True})
  if status!='Success':raise ValueError('IK_REJECTED:'+status)
  delta=ik[self.arm_indices]-q[self.arm_indices];duration=max(.5,float(np.max(np.abs(delta)))*3);n=int(np.ceil(duration/self.cfg['scene']['dt']))
  if n>2500:raise ValueError('ACTION_DURATION_LIMIT')
  u=np.linspace(0,1,n);pos=q[self.arm_indices]+(3*u*u-2*u*u*u)[:,None]*delta;vel=(6*u-6*u*u)[:,None]*delta/duration
  return {'position':pos,'velocity':vel,'start_full':q.copy(),'target_tcp':p.tolist()}
 def move_tcp(self,pose):return self.world.execute_group({self.side:{'pose':pose}})

class DualScene:
 def __init__(self,output):
  import sapien,mplib
  mplib.set_global_seed(2);np.random.seed(2)
  self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=False);self.phase_name='setup';self.steps=0;self.dt=.004;self.writer=None;self.records=[]
  source=self.output/'source_snapshot';source.mkdir()
  for path in Path(__file__).parent.iterdir():
   if path.suffix in ('.py','.sh'):(source/path.name).write_bytes(path.read_bytes())
  write_json(source/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()})
  # Original constructor creates the single shared table, object, first articulation.
  base=RM65Scene(self.output/'left',settle=False);self.scene=base.scene;self.cube=base.cube;self.cube_body=base.cube_body;self.table=base.table;self.cfg=base.cfg
  left=Arm.__new__(Arm);left.__dict__.update(base.__dict__);left.prefix='L__';left.side='left';left.world=self;left.robot.name='left_rm65'
  for link in left.robot.get_links():
   name='L__'+link.name;link.name=name;link.entity.name=name
  self.arms={'left':left}
  right=Arm.__new__(Arm);right.__dict__.update(base.__dict__);right.output=self.output/'right';right.output.mkdir();right.prefix='R__';right.side='right';right.world=self;right.cfg=copy.deepcopy(base.cfg);right.cfg['temporary_assembly']['base_world_xyz_m']=[.75,-.3,.03]
  right.events=(right.output/'events.jsonl').open('x',buffering=1);right.motion=None;right.action_count=0;right.arm_target=np.zeros(6);right.stopped=threading.Event()
  loader=self.scene.create_urdf_loader();loader.fix_root_link=True;loader.set_material(.5,.5,0.);right.robot=loader.load(str(CONFIG/'assembly.urdf'),str(CONFIG/'assembly.srdf'));right.robot.name='right_rm65';right.robot.set_root_pose(sapien.Pose([.75,-.3,.03],[0,0,0,1]))
  right.joints=right.robot.get_active_joints();right.names=[j.name for j in right.joints];right.links={x.name:x for x in right.robot.get_links()};right.arm_indices=[right.names.index('joint'+str(i)) for i in range(1,7)];right.master=right.names.index(right.cfg['gripper_master'])
  for link in right.robot.get_links():
   name='R__'+link.name;link.name=name;link.entity.name=name
  q=np.zeros(len(right.names));right.robot.set_qpos(q)
  for i,j in enumerate(right.joints):
   limit=right.tree.find(f"joint[@name='{j.name}']/limit");c=right.cfg['control']
   if i in right.arm_indices:j.set_drive_property(c['arm_stiffness'],c['arm_damping'],force_limit=float(limit.get('effort')))
   elif i==right.master:j.set_drive_property(c['gripper_stiffness'],c['gripper_damping'],force_limit=float(limit.get('effort')))
   else:j.set_drive_property(0.,.1,force_limit=float(limit.get('effort')))
   j.set_drive_target(0.)
  b=self.scene.create_actor_builder();b.add_box_collision(half_size=[.06,.06,.015],material=base.material);b.add_box_visual(half_size=[.06,.06,.015],material=[.15]*3);right.stand=b.build_static(name='right_mounting_stand');right.stand.set_pose(sapien.Pose([.75,-.3,.015]));self.arms['right']=right
  
  self.scene.remove_actor(base.zone)
  marker=self.scene.create_actor_builder();marker.add_box_visual(half_size=[.07,.07,.0005],material=[.03,.15,.85]);base.zone=marker.build_static(name='placement_marker');base.zone.set_pose(sapien.Pose([.60,.16,.0006]));self.target_xy=[.60,.16]
  self.cameras={'table':base.cameras['fixed'],'left_wrist':base.cameras['wrist']};self.cameras['table'].set_pose(camera_pose([.95,-1.0,.85],[.375,0,.24]));c=base.cfg['camera'];self.cameras['right_wrist']=self.scene.add_camera('right_wrist',c['width'],c['height'],math.radians(c['fovy_degrees']),.01,5)
  self.logfile=(self.output/'physics.jsonl').open('x',buffering=1);self.group_count=0;self.tick(100)
  write_json(self.output/'configuration.json',{'source':'two RM65 in one SAPIEN Scene','scene_identity':id(self.scene),'articulations':len(self.scene.get_all_articulations()),'world_frame':'SAPIEN world metres/wxyz','left_base':[0,0,.03,1,0,0,0],'right_base':[.75,-.3,.03,0,0,0,1],'target_xy':self.target_xy,'dt':self.dt,'original_config':self.cfg,'controller':'closest mplib IK + cubic joint interpolation + full shared-world FCL checks; no OMPL rerouting','physical_weld':False,'runtime_object_pose_writes':False})
 def contacts(self):
  return [{'names':[b.entity.name for b in c.bodies],'points':[{'p':p.position.tolist(),'impulse':p.impulse.tolist(),'separation':float(p.separation)} for p in c.points if np.linalg.norm(p.impulse)>1e-7]} for c in self.scene.get_contacts() if any(np.linalg.norm(p.impulse)>1e-7 for p in c.points)]
 def tick(self,n):
  for _ in range(n):
   if any(a.stopped.is_set() for a in self.arms.values()):raise RuntimeError('WORLD_STOPPED')
   for a in self.arms.values():a.robot.set_qf(a.robot.compute_passive_force(gravity=True,coriolis_and_centrifugal=True))
   self.scene.step();self.steps+=1
   for a in self.arms.values():a.step=self.steps;a.monitor()
   cs=self.contacts();pose=self.cube.get_pose();row={'step':self.steps,'sim_time_s':self.steps*self.dt,'wall_time':time.time(),'phase':self.phase_name,'object_pose':[*pose.p.tolist(),*pose.q.tolist()],'object_velocity':self.cube_body.get_linear_velocity().tolist(),'arms':{s:a.state() for s,a in self.arms.items()},'bilateral_contact':{s:a.bilateral_pad_contact() for s,a in self.arms.items()},'contacts':cs}
   self.records.append(row);self.logfile.write(json.dumps(row)+'\n')
   for c in cs:
    names=c['names'];separation=min(p['separation'] for p in c['points'])
    if any(x.startswith('L__') for x in names) and any(x.startswith('R__') for x in names):raise RuntimeError('INTERARM_CONTACT:'+str(names))
    for s,a in self.arms.items():
     own=[x[len(a.prefix):] for x in names if x.startswith(a.prefix)]
     if len(own)==2 and frozenset(own) not in a.ignore and separation<-.002:raise RuntimeError('SELF_COLLISION:'+str(names))
     if len(own)==1 and separation<-.002:
      other=next(x for x in names if not x.startswith(a.prefix))
      allowed=(other in ['table',a.stand.name] and own[0]=='base_link') or (other=='target_cube' and own[0] in a.pad_vertices)
      if other=='target_cube' and own[0] in a.pad_vertices:raise RuntimeError('PAD_PENETRATION')
      if other in ['table','mounting_stand','right_mounting_stand','target_cube'] and not allowed:raise RuntimeError('SCENE_COLLISION:'+str(names))
   if self.writer is not None and self.steps%25==0:self.frame()
 def observe(self,folder):
  from PIL import Image
  folder=Path(folder);folder.mkdir();images=[];calibration={}
  for s in ['left','right']:self.cameras[s+'_wrist'].set_pose(self.arms[s].links['ctag_base_link'].get_pose()*self.arms[s].wrist_relative)
  self.scene.update_render()
  for name,cam in self.cameras.items():
   cam.take_picture();rgb=(np.clip(cam.get_picture('Color')[:,:,:3],0,1)*255).astype('uint8');p=folder/(name+'.png');Image.fromarray(rgb).save(p);images.append(str(p));calibration[name]={'intrinsic_cv':cam.get_intrinsic_matrix().tolist(),'world_to_camera_cv':cam.get_extrinsic_matrix().tolist(),'camera_to_world_gl':cam.get_model_matrix().tolist(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  obs={'images':images,'calibration':calibration,'arms':{s:a.state() for s,a in self.arms.items()},'world':'SAPIEN world metres','tcp':'actual pad center; orientation Link6 quaternion wxyz','sim_time_s':self.steps*self.dt};write_json(folder/'observation.json',obs);return obs
 def start_video(self):
  import imageio.v2 as imageio
  self.writer=imageio.get_writer(str(self.output/'execution.mp4'),fps=10,codec='libx264',macro_block_size=1);self.frame()
 def frame(self):
  frames=[]
  for s in ['left','right']:self.cameras[s+'_wrist'].set_pose(self.arms[s].links['ctag_base_link'].get_pose()*self.arms[s].wrist_relative)
  self.scene.update_render()
  for cam in self.cameras.values():cam.take_picture();frames.append((np.clip(cam.get_picture('Color')[:,:,:3],0,1)*255).astype('uint8'))
  self.writer.append_data(np.concatenate(frames,axis=1))
 def execute_group(self,commands):
  from mplib.sapien_utils.conversion import convert_object_name
  self.group_count+=1;folder=self.output/f'group_{self.group_count:03d}';folder.mkdir();write_json(folder/'proposal.json',commands);plans={}
  try:
   for s,c in commands.items():
    if s not in self.arms or set(c) not in ({'pose'},{'opening'}):raise ValueError('NUMERIC_ACTION_ONLY')
    if 'pose' in c:plans[s]=self.arms[s].plan_tcp(c['pose'])
    else:
     a=self.arms[s];opening=c['opening']
     if isinstance(opening,bool) or not np.isfinite(opening) or not 0<=opening<=1:raise ValueError('INVALID_OPENING')
     q=a.robot.get_qpos().copy();target=-.91*(1-opening)
     plans[s]={'position':np.tile(q[a.arm_indices],(350,1)),'velocity':np.zeros((350,6)),'start_full':q,'grip_targets':np.r_[np.linspace(q[a.master],target,150),np.repeat(target,200)],'closing':target<q[a.master]}

   n=max(len(x['position']) for x in plans.values())
   # Full shared world at each interpolated simultaneous configuration; reject all before execution.
   for a in self.arms.values():
    if a.motion is None:a.init_planner()
    a.motion.update_from_simulation()
   for i in range(n):
    qs={s:a.robot.get_qpos().copy() for s,a in self.arms.items()}
    for s,plan in plans.items():
     a=self.arms[s];qs[s][a.arm_indices]=plan['position'][min(i,len(plan['position'])-1)]
     if 'grip_targets' in plan:
      qs[s][a.master]=plan['grip_targets'][min(i,349)]
      for name,(parent,mult,off) in a.mimics.items():qs[s][a.names.index(name)]=qs[s][a.names.index(parent)]*mult+off
    for s,a in self.arms.items():
     world=a.motion.planning_world
     for other,oa in self.arms.items():world.get_articulation(convert_object_name(oa.robot)).set_qpos(qs[other],full=True)
     if a.motion.check_for_self_collision(qs[s]) or a.motion.check_for_env_collision(qs[s]):raise ValueError('INTERPOLATED_COLLISION:'+s+':'+str(i))
   for s,plan in plans.items():np.savez_compressed(folder/(s+'_trajectory.npz'),**plan)
  except (ValueError,RuntimeError) as e:
   result={'ok':False,'executed':False,'reason':str(e)};write_json(folder/'receipt.json',result);return result
  self.phase_name='numeric_group_'+str(self.group_count);start=self.steps;latched=set();contact_steps={s:0 for s in plans}
  for s,plan in plans.items():
   if 'grip_targets' in plan:
    a=self.arms[s];master=a.joints[a.master];limit=float(a.tree.find(f"joint[@name='{master.name}']/limit").get('effort'));master.set_drive_property(a.cfg['control']['gripper_stiffness'],a.cfg['control']['gripper_damping'],force_limit=limit)
  try:
   for i in range(n):
    for s,plan in plans.items():
     a=self.arms[s];idx=min(i,len(plan['position'])-1);p=plan['position'][idx];v=plan['velocity'][idx] if i<len(plan['position']) else np.zeros(6);a.arm_target=p.copy()
     for j,qi,vi in zip(a.arm_indices,p,v):a.joints[j].set_drive_target(float(qi));a.joints[j].set_drive_velocity_target(float(vi))
     if 'grip_targets' in plan and s not in latched:a.joints[a.master].set_drive_target(float(plan['grip_targets'][min(i,349)]))
    self.tick(1)
    for s,plan in plans.items():
     if 'grip_targets' in plan and plan['closing'] and s not in latched:
      contact_steps[s]=contact_steps[s]+1 if self.arms[s].bilateral_pad_contact() else 0
      if contact_steps[s]>=2:self.arms[s].latch_grasp_contact();latched.add(s)
   for s in plans:
    for i in self.arms[s].arm_indices:self.arms[s].joints[i].set_drive_velocity_target(0.)
   self.tick(100)
   result={'ok':True,'executed':True,'start_step':start,'end_step':self.steps,'actual_states':{s:a.state() for s,a in self.arms.items()}}
  except BaseException as e:
   for a in self.arms.values():a.stopped.set();a.hold()
   write_json(folder/'receipt.json',{'ok':False,'executed':'PARTIAL','error':repr(e)});raise
  write_json(folder/'receipt.json',result);return result
 def close(self):
  if self.writer is not None:self.writer.close()
  self.logfile.close()
  for a in self.arms.values():
   a.hold();a.events.close()
  for handle in [self.arms['left'].private,self.arms['left'].diag]:
   if hasattr(handle,'close'):handle.close()
