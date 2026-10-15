"""Private collision representation only. Never moves/welds a PhysX body or edits a goal.
Predict the held body's pose from the holder's candidate FK while retaining all
original pad exceptions and all inter-arm/object-environment collision checks.
"""
import numpy as np
import mplib
from mplib.sapien_utils.conversion import convert_object_name
from mplib.collision_detection.fcl import FCLObject

def install(scene,arm):
 world=arm.motion.planning_world;original_check=world.check_collision
 def update_and_check():
  holder=getattr(scene,'collision_holder',None)
  if holder is None:return []
  owner=scene.arms[holder];model=world.get_articulation(convert_object_name(owner.robot));pin=model.get_pinocchio_model();q=model.get_qpos();pin.compute_forward_kinematics(q);idx=pin.get_link_names().index(owner.prefix+'Link6');flange=model.get_base_pose()*pin.get_link_pose(idx)
  pose=flange*scene.collision_holder_relative_pose;name=convert_object_name(scene.cube);old=world.get_object(name);world.add_object(FCLObject(name,pose,old.shapes,old.shape_poses))
  extra=[]
  # Object vs table/stands/other actors and BOTH robots remains checked.
  for entity in scene.scene.get_all_actors():
   if entity is not scene.cube and convert_object_name(entity)!=name and world.get_object(convert_object_name(entity)) is not None:extra+=world.check_collision_between(scene.cube,entity,acm=arm.motion.acm)
  for robot in scene.arms.values():extra+=world.check_collision_between(scene.cube,robot.robot,acm=arm.motion.acm)
  return extra
 def checked():
  extra=update_and_check();return original_check()+extra
 world.check_collision=checked
 arm.motion.carry_collision_update=update_and_check
 # Original expert calls these helpers directly during dense path validation.
 for name in ['check_for_env_collision','check_for_self_collision']:
  original=getattr(arm.motion,name)
  def wrapper(*args,_original=original,**kwargs):
   if args:arm.motion.robot.set_qpos(args[0],True)
   extra=update_and_check();return _original(*args,**kwargs)+extra
  setattr(arm.motion,name,wrapper)

def prepare(scene,commands=None):
 commands=commands or {};held=[s for s,a in scene.arms.items() if a.bilateral_pad_contact()]
 releasing=[s for s,c in commands.items() if 'opening' in c and c['opening']>.8]
 eligible=[s for s in held if s not in releasing];previous=getattr(scene,'collision_holder',None)
 holder=previous if previous in eligible else (eligible[0] if eligible else None)
 scene.collision_holder=holder;scene.collision_holder_relative_pose=None
 if holder:
  a=scene.arms[holder];p=a.links['Link6'].get_pose();obj=scene.cube.get_pose();scene.collision_holder_relative_pose=mplib.Pose(p.p,p.q).inv()*mplib.Pose(obj.p,obj.q)
 for arm in scene.arms.values():
  if arm.motion is None:arm.init_planner()
  arm.motion.update_from_simulation();arm.motion.carry_collision_update()
 return {'holder':holder,'actual_bilateral':held,'releasing_commands':releasing,'representation':'FK-following FCL only; PhysX free dynamic body unchanged','original_pad_exceptions_only':True}
