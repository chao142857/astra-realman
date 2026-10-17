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

LAYOUT=json.loads(Path(os.environ.get('RM65_LAYOUT',str(Path(__file__).parent/'scene_v1.json'))).read_text())
def initial_arm_q(side):
 return LAYOUT['initial_arm_q_by_side'][side] if 'initial_arm_q_by_side' in LAYOUT else LAYOUT['initial_arm_q']
from mimic_control import damped_mimic
CONTROLLER=os.environ.get('RM65_CONTROLLER','original')
if CONTROLLER not in ('original','damped_mimic_v1','light_latch_v1','urdf_effort_hold_v2'):raise ValueError('UNKNOWN_CONTROLLER')
# New configuration only; original source/assets and V0 remain immutable.
import shutil,rm65_scene as source_scene
ORIGINAL_CONFIG=CONFIG
CONFIG=Path(__file__).parent/'runtime_config'
CONFIG.mkdir(exist_ok=True)
for path in ORIGINAL_CONFIG.iterdir():
 if path.is_file():shutil.copy2(path,CONFIG/path.name)
cfg=json.loads((CONFIG/'assembly.json').read_text())
for key in ('table_center','table_half_size','cube_initial_xyz'):cfg['scene'][key]=LAYOUT[key]
cfg['temporary_assembly']['base_world_xyz_m']=LAYOUT['left_base'][:3]
cfg['scene']['place_zone_xy']=LAYOUT['target_xy'];cfg['control']['initial_arm_q']=initial_arm_q('left')
(CONFIG/'assembly.json').write_text(json.dumps(cfg,indent=2))
source_scene.CONFIG=CONFIG

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
  from carry_collision import install
  install(self.world,self)
 def bilateral_pad_contact(self):
  touching=set()
  for c in self.scene.get_contacts():
   names=[b.entity.name for b in c.bodies]
   if 'target_cube' not in names:continue
   for n in names:
    if n in [self.prefix+p for p in self.pad_vertices] and any(p.separation<=.0002 and np.linalg.norm(p.impulse)>1e-6 for p in c.points):touching.add(n)
  return len(touching)==2
 def latch_grasp_contact(self):
  result=super().latch_grasp_contact()
  if CONTROLLER=='light_latch_v1':
   self.joints[self.master].set_drive_property(self.cfg['control']['gripper_stiffness'],self.cfg['control']['gripper_damping'],force_limit=.05)
   self.log('v1_contact_latch_force',{'force_limit_Nm':.05,'original_force_limit_Nm':.1,'preload_unchanged_rad':.005})
  elif CONTROLLER=='urdf_effort_hold_v2':
   # Independent actuator variant: retain the same contact target/preload and
   # spring gains, but allow the URDF actuator authority in both directions.
   # The old 0.1 Nm saturation also caps corrective OPENING torque when the
   # measured master is already more closed than its fixed target.
   master=self.joints[self.master]
   effort=float(self.tree.find(f"joint[@name='{master.name}']/limit").get('effort'))
   master.set_drive_property(self.cfg['control']['gripper_stiffness'],self.cfg['control']['gripper_damping'],force_limit=effort)
   result=dict(result,controller_variant=CONTROLLER,force_limit_Nm=effort,nominal_preload_unchanged=True)
   self.log('urdf_effort_contact_hold_v2',result)
  return result
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
  from carry_collision import prepare
  prepare(self.world,getattr(self.world,'pending_collision_commands',None))
  goal=self.motion._transform_goal_to_wrt_base(mplib.Pose(fp[:3],fp[3:]));mask=np.ones(len(q),dtype=bool);mask[self.arm_indices]=False
  status,ik=self.motion.IK(goal,q,mask=mask,return_closest=True)
  self.log('numeric_ik',{'target_tcp':p.tolist(),'target_flange':fp.tolist(),'status':status,'start_qpos':q.tolist(),'goal_qpos':None if ik is None else ik.tolist(),'no_target_correction':True})
  if status!='Success':
   pure,ok,_=self.motion.pinocchio_model.compute_IK_CLIK(self.motion.link_name_2_idx[self.motion.move_group],goal,q,mask)
   limit_ok=bool(ok and self.motion.wrap_joint_limit(pure));pairs=[]
   if limit_ok:
    self.motion.robot.set_qpos(pure,True);pairs=[(x.object_name1,x.link_name1,x.object_name2,x.link_name2) for x in self.motion.planning_world.check_collision()]
   diagnosis={'pure_clik_success':bool(ok),'within_joint_limits':limit_ok,'collision_pairs':pairs,'goal_unchanged':True};self.log('numeric_ik_rejection_diagnosis',diagnosis)
   code='COLLISION' if pairs else ('JOINT_LIMIT' if ok and not limit_ok else 'NO_VALID_SOLUTION')
   raise ValueError('IK_REJECTED_'+code+':'+str(diagnosis))
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
   if path.suffix in ('.py','.sh','.json'):(source/path.name).write_bytes(path.read_bytes())
  write_json(source/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()})
  # Original constructor creates the single shared table, object, first articulation.
  with damped_mimic(CONTROLLER=='damped_mimic_v1'):base=RM65Scene(self.output/'left',settle=False)
  # Layout initialization, before any physics steps. The original constructor
  # hard-codes the left stand at x=y=0 and supports only root translation.
  base.robot.set_root_pose(sapien.Pose(LAYOUT['left_base'][:3],LAYOUT['left_base'][3:]))
  base.stand.set_pose(sapien.Pose([*LAYOUT['left_base'][:2],.015]))
  self.scene=base.scene;self.cube=base.cube;self.cube_body=base.cube_body;self.table=base.table;self.cfg=base.cfg
  left=Arm.__new__(Arm);left.__dict__.update(base.__dict__);left.prefix='L__';left.side='left';left.world=self;left.robot.name='left_rm65'
  for link in left.robot.get_links():
   name='L__'+link.name;link.name=name;link.entity.name=name
  self.arms={'left':left}
  right=Arm.__new__(Arm);right.__dict__.update(base.__dict__);right.output=self.output/'right';right.output.mkdir();right.prefix='R__';right.side='right';right.world=self;right.cfg=copy.deepcopy(base.cfg);right.cfg['temporary_assembly']['base_world_xyz_m']=LAYOUT['right_base'][:3]
  right.events=(right.output/'events.jsonl').open('x',buffering=1);right.motion=None;right.action_count=0;right.arm_target=np.zeros(6);right.stopped=threading.Event()
  loader=self.scene.create_urdf_loader();loader.fix_root_link=True;loader.set_material(.5,.5,0.);
  with damped_mimic(CONTROLLER=='damped_mimic_v1'):right.robot=loader.load(str(CONFIG/'assembly.urdf'),str(CONFIG/'assembly.srdf'))
  right.robot.name='right_rm65';right.robot.set_root_pose(sapien.Pose(LAYOUT['right_base'][:3],LAYOUT['right_base'][3:]))
  right.joints=right.robot.get_active_joints();right.names=[j.name for j in right.joints];right.links={x.name:x for x in right.robot.get_links()};right.arm_indices=[right.names.index('joint'+str(i)) for i in range(1,7)];right.master=right.names.index(right.cfg['gripper_master'])
  for link in right.robot.get_links():
   name='R__'+link.name;link.name=name;link.entity.name=name
  right.cfg['control']['initial_arm_q']=initial_arm_q('right')
  q=np.zeros(len(right.names));q[right.arm_indices]=initial_arm_q('right');right.arm_target=q[right.arm_indices].copy();right.robot.set_qpos(q)
  for i,j in enumerate(right.joints):
   limit=right.tree.find(f"joint[@name='{j.name}']/limit");c=right.cfg['control']
   if i in right.arm_indices:j.set_drive_property(c['arm_stiffness'],c['arm_damping'],force_limit=float(limit.get('effort')))
   elif i==right.master:j.set_drive_property(c['gripper_stiffness'],c['gripper_damping'],force_limit=float(limit.get('effort')))
   else:j.set_drive_property(0.,.1,force_limit=float(limit.get('effort')))
   j.set_drive_target(float(q[i]))
  b=self.scene.create_actor_builder();b.add_box_collision(half_size=[.06,.06,.015],material=base.material);b.add_box_visual(half_size=[.06,.06,.015],material=[.15]*3);right.stand=b.build_static(name='right_mounting_stand');right.stand.set_pose(sapien.Pose([*LAYOUT['right_base'][:2],.015]));self.arms['right']=right

  solver_mode=os.environ.get('RM65_SOLVER','original')
  if solver_mode not in ('original','refined_v1'):raise ValueError('UNKNOWN_SOLVER')
  bodies=[self.cube_body]+[a.robot for a in self.arms.values()]
  solver_before=[{'position':b.get_solver_position_iterations(),'velocity':b.get_solver_velocity_iterations()} for b in bodies]
  if solver_mode=='refined_v1':
   for b in bodies:b.set_solver_position_iterations(32);b.set_solver_velocity_iterations(8)
  self.solver_record={'mode':solver_mode,'before':solver_before,'after':[{'position':b.get_solver_position_iterations(),'velocity':b.get_solver_velocity_iterations()} for b in bodies]}
  # Visual palette only; collision shapes/materials and controller are unchanged.
  def paint(entity,color):
   body=entity.find_component_by_type(sapien.render.RenderBodyComponent)
   if body:
    material=sapien.render.RenderMaterial(base_color=[*color,1.],roughness=.8,metallic=0.,specular=.2)
    for shape in body.render_shapes:
     shape.material.set_base_color([*color,1.]);shape.material.set_roughness(.8)
  paint(self.table,[.35,.20,.10])
  for arm in self.arms.values():
   for name,link in arm.links.items():paint(link.entity,[.10,.11,.12] if name.startswith('ctag') else [.82,.82,.77])
  self.scene.remove_actor(base.zone)
  marker=self.scene.create_actor_builder();marker.add_box_visual(half_size=[.07,.07,.0005],material=[.03,.15,.85]);base.zone=marker.build_static(name='placement_marker');base.zone.set_pose(sapien.Pose([*LAYOUT['target_xy'],.0006]));self.target_xy=LAYOUT['target_xy']
  self.cameras={};c=base.cfg['camera']
  for role,setting in LAYOUT['cameras'].items():
   cam=self.scene.add_camera(role,c['width'],c['height'],math.radians(setting['fovy_degrees']),.01,5);self.cameras[role]=cam
   if 'position' in setting:cam.set_pose(camera_pose(setting['position'],setting['look_at']))
   else:self.arms[role.split('_')[0]].wrist_relative=camera_pose(setting['position_parent'],setting['look_at_parent'])
  self.preview_camera=self.scene.add_camera('scene_preview_NOT_MODEL_INPUT',960,720,math.radians(55),.01,5)
  self.preview_camera.set_pose(camera_pose(LAYOUT['preview']['position'],LAYOUT['preview']['look_at']))
  self.logfile=(self.output/'physics.jsonl').open('x',buffering=1);self.group_count=0;self.tick(100)
  write_json(self.output/'configuration.json',{'source':'two RM65 in one SAPIEN Scene','scene_identity':id(self.scene),'articulations':len(self.scene.get_all_articulations()),'world_frame':'SAPIEN world metres/wxyz','left_base':LAYOUT['left_base'],'right_base':LAYOUT['right_base'],'layout':LAYOUT,'target_xy':self.target_xy,'solver':self.solver_record,'dt':self.dt,'gripper_latched_force_limit_Nm':(.05 if CONTROLLER=='light_latch_v1' else (float(left.tree.find(f"joint[@name='{left.joints[left.master].name}']/limit").get('effort')) if CONTROLLER=='urdf_effort_hold_v2' else .1)),'mimic_controller':CONTROLLER,'mimic_damping':5. if CONTROLLER=='damped_mimic_v1' else 0.,'original_config':self.cfg,'controller':'closest mplib IK + cubic joint interpolation + full shared-world FCL checks; no OMPL rerouting','physical_weld':False,'runtime_object_pose_writes':False})
 def contacts(self):
  return [{'names':[b.entity.name for b in c.bodies],'points':[{'p':p.position.tolist(),'impulse':p.impulse.tolist(),'separation':float(p.separation)} for p in c.points if np.linalg.norm(p.impulse)>1e-7]} for c in self.scene.get_contacts() if any(np.linalg.norm(p.impulse)>1e-7 for p in c.points)]
 def tick(self,n):
  for _ in range(n):
   if any(a.stopped.is_set() for a in self.arms.values()):raise RuntimeError('WORLD_STOPPED')
   for a in self.arms.values():a.robot.set_qf(a.robot.compute_passive_force(gravity=True,coriolis_and_centrifugal=True))
   self.scene.step();self.steps+=1
   for a in self.arms.values():a.step=self.steps;a.monitor()
   cs=self.contacts();pose=self.cube.get_pose();row={'step':self.steps,'sim_time_s':self.steps*self.dt,'wall_time':time.time(),'phase':self.phase_name,'object_pose':[*pose.p.tolist(),*pose.q.tolist()],'object_velocity':self.cube_body.get_linear_velocity().tolist(),'drive_targets':{s:[float(j.get_drive_target()[0]) for j in a.joints] for s,a in self.arms.items()},'arms':{s:a.state() for s,a in self.arms.items()},'bilateral_contact':{s:a.bilateral_pad_contact() for s,a in self.arms.items()},'contacts':cs}
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
   cam.take_picture();rgb=(np.clip(cam.get_picture('Color')[:,:,:3],0,1)*255).astype('uint8');p=folder/(name+'.png');Image.fromarray(rgb).save(p);images.append(str(p));calibration[name]={'role':name,'resolution':[640,480],'observation_sim_time_s':self.steps*self.dt,'observation_wall_time':time.time(),'intrinsic_cv':cam.get_intrinsic_matrix().tolist(),'world_to_camera_cv':cam.get_extrinsic_matrix().tolist(),'camera_to_world_gl':cam.get_model_matrix().tolist(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  self.preview_camera.take_picture();Image.fromarray((np.clip(self.preview_camera.get_picture('Color')[:,:,:3],0,1)*255).astype('uint8')).save(folder/'scene_preview_NOT_MODEL_INPUT.png')
  tiles=[np.asarray(Image.open(path)) for path in images];Image.fromarray(np.vstack([np.hstack(tiles[:2]),np.hstack(tiles[2:])])).save(folder/'four_views.png')
  obs={'images':images,'calibration':calibration,'arms':{s:a.state() for s,a in self.arms.items()},'base_transforms_world_wxyz':{'left':LAYOUT['left_base'],'right':LAYOUT['right_base']},'world':'SAPIEN world metres','tcp':'actual pad center; orientation Link6 quaternion wxyz','sim_time_s':self.steps*self.dt};write_json(folder/'observation.json',obs);return obs
 def start_video(self):
  import imageio.v2 as imageio
  self.writer=imageio.get_writer(str(self.output/'execution.mp4'),fps=10,codec='libx264',macro_block_size=1);self.frame()
 def frame(self):
  frames=[]
  for s in ['left','right']:self.cameras[s+'_wrist'].set_pose(self.arms[s].links['ctag_base_link'].get_pose()*self.arms[s].wrist_relative)
  self.scene.update_render()
  for cam in self.cameras.values():cam.take_picture();frames.append((np.clip(cam.get_picture('Color')[:,:,:3],0,1)*255).astype('uint8'))
  self.writer.append_data(np.vstack([np.hstack(frames[:2]),np.hstack(frames[2:])]))
 def execute_group(self,commands):
  from mplib.sapien_utils.conversion import convert_object_name
  self.pending_collision_commands=commands
  from carry_collision import prepare
  collision_state=prepare(self,commands)
  self.group_count+=1;folder=self.output/f'group_{self.group_count:03d}';folder.mkdir();write_json(folder/'proposal.json',commands);write_json(folder/'collision_representation_PRIVATE.json',collision_state);plans={}
  try:
   for s,c in commands.items():
    if s not in self.arms or set(c) not in ({'pose'},{'opening'},{'opening','contact_mode'}):raise ValueError('NUMERIC_ACTION_ONLY')
    if 'pose' in c:plans[s]=self.arms[s].plan_tcp(c['pose'])
    else:
     a=self.arms[s];opening=c['opening']
     if isinstance(opening,bool) or not np.isfinite(opening) or not 0<=opening<=1:raise ValueError('INVALID_OPENING')
     q=a.robot.get_qpos().copy();target=-.91*(1-opening)
     scale=getattr(self,'contact_closure_time_scale',1) if c.get('contact_mode')=='bilateral_hold' and target<q[a.master] else 1
     if scale not in (1,2):raise ValueError('UNVALIDATED_CONTACT_CLOSURE_TIMING')
     ramp_steps=150*scale;grip_steps=ramp_steps+200
     plans[s]={'position':np.tile(q[a.arm_indices],(grip_steps,1)),'velocity':np.zeros((grip_steps,6)),'start_full':q,'grip_targets':np.r_[np.linspace(q[a.master],target,ramp_steps),np.repeat(target,200)],'closing':target<q[a.master], 'contact_closure_time_scale':scale}
     if 'contact_mode' in c:
      if c['contact_mode'] not in ('position','bilateral_hold'):raise ValueError('INVALID_CONTACT_MODE')
      plans[s].update(contact_mode=c['contact_mode'],requested_master_target=target)

   from contact_preflight_v2 import deferred_closing
   contact_deferred=deferred_closing(plans)
   write_json(folder/'preflight_policy.json',{'version':'rm65.contact_dependent_preflight.v2',
    'deferred_closing_sides':contact_deferred,'static_arm_and_other_motion_checked':True,
    'closure_safety':'CONTACT_DEPENDENT_NOT_PROVEN_BY_EMPTY_SPACE_RAMP' if contact_deferred else 'FULL_DETERMINISTIC_TRAJECTORY',
    'actual_scene_queries':'before/after every physics step and settling; original ACM only',
    'native_2mm_monitor_unchanged':True})
   n=max(len(x['position']) for x in plans.values())
   # Deterministic arm/other motion preflight. Contact-dependent fingers remain
   # measured here; their outcome is explicitly deferred to per-step guarding.
   for a in self.arms.values():
    if a.motion is None:a.init_planner()
    a.motion.update_from_simulation()
   for i in range(n):
    qs={s:a.robot.get_qpos().copy() for s,a in self.arms.items()}
    for s,plan in plans.items():
     a=self.arms[s];qs[s][a.arm_indices]=plan['position'][min(i,len(plan['position'])-1)]
     if 'grip_targets' in plan and s not in contact_deferred:
      qs[s][a.master]=plan['grip_targets'][min(i,len(plan['grip_targets'])-1)]
      for name,(parent,mult,off) in a.mimics.items():qs[s][a.names.index(name)]=qs[s][a.names.index(parent)]*mult+off
    for s,a in self.arms.items():
     world=a.motion.planning_world
     for other,oa in self.arms.items():world.get_articulation(convert_object_name(oa.robot)).set_qpos(qs[other],full=True)
     collisions=world.check_collision()
     if collisions:raise ValueError('INTERPOLATED_COLLISION:'+s+':'+str(i)+':'+str([(c.object_name1,c.link_name1,c.object_name2,c.link_name2) for c in collisions]))
   for s,plan in plans.items():np.savez_compressed(folder/(s+'_trajectory.npz'),**plan)
  except (ValueError,RuntimeError) as e:
   result={'ok':False,'executed':False,'reason':str(e)};write_json(folder/'receipt.json',result);return result
  self.phase_name=getattr(self,'phase_context',None) or 'numeric_group_'+str(self.group_count);start=self.steps;latched=set();contact_steps={s:0 for s in plans}
  for s,plan in plans.items():
   if 'grip_targets' in plan:
    a=self.arms[s];master=a.joints[a.master];limit=float(a.tree.find(f"joint[@name='{master.name}']/limit").get('effort'));master.set_drive_property(a.cfg['control']['gripper_stiffness'],a.cfg['control']['gripper_damping'],force_limit=limit)
  guard=None
  if contact_deferred:
   from contact_preflight_v2 import ContactGuard
   guard=ContactGuard(self,folder,commands,contact_deferred)
  try:
   for i in range(n):
    for s,plan in plans.items():
     a=self.arms[s];idx=min(i,len(plan['position'])-1);p=plan['position'][idx];v=plan['velocity'][idx] if i<len(plan['position']) else np.zeros(6);a.arm_target=p.copy()
     for j,qi,vi in zip(a.arm_indices,p,v):a.joints[j].set_drive_target(float(qi));a.joints[j].set_drive_velocity_target(float(vi))
     if 'grip_targets' in plan and s not in latched:a.joints[a.master].set_drive_target(float(plan['grip_targets'][min(i,len(plan['grip_targets'])-1)]))
    if guard:guard.check('before_physics',i,latched)
    self.tick(1)
    if guard:guard.check('after_physics',i,latched)
    for s,plan in plans.items():
     if 'grip_targets' in plan and plan['closing'] and plan.get('contact_mode')!='position' and s not in latched:
      contact_steps[s]=contact_steps[s]+1 if self.arms[s].bilateral_pad_contact() else 0
      if contact_steps[s]>=2:
       a=self.arms[s];a.latch_grasp_contact();latched.add(s)
       if 'contact_mode' in plan:
        # V2 explicit hold: sensed bilateral contact, existing finite preload,
        # bounded by the caller's empty-space closure target. No task/GT target.
        j=a.joints[a.master];target=max(plan['requested_master_target'],float(j.get_drive_target()[0]))
        j.set_drive_target(target)
        a.log('explicit_contact_hold',{'requested_opening_fraction':commands[s]['opening'],
         'requested_master_target':plan['requested_master_target'],'held_master_target':target,
         'servo_target_within_requested_closure':True})
   for s in plans:
    for i in self.arms[s].arm_indices:self.arms[s].joints[i].set_drive_velocity_target(0.)
   post_hold_start=self.steps
   if guard:
    for settle_i in range(getattr(self,'numeric_post_hold_steps',100)):
     self.tick(1);guard.check('settling',settle_i,latched)
   else:self.tick(getattr(self,'numeric_post_hold_steps',100))
   residuals={}
   for s,plan in plans.items():
    if 'target_tcp' in plan:
     state=self.arms[s].state();target=np.array(plan['target_tcp']);actual=np.array(state['actual_grasp_center_world']);rotation=(Rotation.from_quat(np.roll(target[3:],-1)).inv()*Rotation.from_quat(np.roll(state['flange_pose_world'][3:],-1))).magnitude()
     residuals[s]={'position_error_m':float(np.linalg.norm(actual-target[:3])),'rotation_error_rad':float(rotation)}
   result={'ok':all(r['position_error_m']<.01 and r['rotation_error_rad']<.05 for r in residuals.values()),'executed':True,'start_step':start,'end_step':self.steps,'goal_residuals':residuals,'actual_states':{s:a.state() for s,a in self.arms.items()}}
   grips={}
   for s,plan in plans.items():
    if 'contact_mode' not in plan:continue
    a=self.arms[s];j=a.joints[a.master];bilateral=a.bilateral_pad_contact()
    grips[s]={'contact_mode':plan['contact_mode'],'requested_opening_fraction':commands[s]['opening'],
     'requested_master_target_rad':plan['requested_master_target'],'actual_master_rad':float(a.robot.get_qpos()[a.master]),
     'servo_target_rad':float(j.get_drive_target()[0]),'actual_representative_pad_gap_m':a.state()['actual_pad_gap_m'],
     'latched':s in latched,'bilateral_contact_at_end':bilateral,'native_drive_torque':None}
    if plan['contact_mode']=='bilateral_hold' and (s not in latched or not bilateral):
     result.update(ok=False,reason='GRIPPER_BILATERAL_HOLD_NOT_ESTABLISHED')
   if grips:
    from gripper_state_v3 import annotate
    result['gripper_execution']=grips;annotate(result)
   if hasattr(self,'numeric_post_hold_steps'):result['post_numeric_observation']={'start_step':post_hold_start,'end_step':self.steps,'duration_s':(self.steps-post_hold_start)*self.dt,'movement_added':False}
  except BaseException as e:
   if guard:
    guard.execution_abort=repr(e);guard.abort_physics_row=self.records[-1] if self.records else None
   for a in self.arms.values():a.stopped.set();a.hold()
   write_json(folder/'receipt.json',{'ok':False,'executed':'PARTIAL','error':repr(e)});raise
  finally:
   if guard:guard.close()
  write_json(folder/'receipt.json',result);return result
 def close(self):
  if self.writer is not None:self.writer.close()
  self.logfile.close()
  for a in self.arms.values():
   a.hold();a.events.close()
  for handle in [self.arms['left'].private,self.arms['left'].diag]:
   if hasattr(handle,'close'):handle.close()
