"""Versioned PhysX mimic construction; original SAPIEN installation is untouched.

Reuses the installed SAPIEN 3.0.0b1 topology and coefficients, stiffness=1e5.
Only adds damping to the internal finger coupling, NOT to cube/robot attachment.
URDF support inertia + parallel-axis contribution is O(1e-4 kg m^2), so
2*sqrt(k*I) is O(6 N m s/rad); 5 is an a-priori order-of-magnitude damping.
No task GT, collision threshold, mass, friction or actuator limit is changed.
"""
from contextlib import contextmanager
@contextmanager
def damped_mimic(enabled):
 if not enabled:
  yield;return
 from sapien.wrapper.articulation_builder import ArticulationBuilder
 original=ArticulationBuilder.build
 def build(self,fix_root_link=None,build_mimic_joints=True):
  import sapien
  assert self.scene is not None
  links=self.build_entities(fix_root_link=fix_root_link)
  articulation=links[0].find_component_by_type(sapien.physx.PhysxArticulationLinkComponent).articulation
  if build_mimic_joints:
   for mimic in self.mimic_joint_records:
    joint=articulation.find_joint_by_name(mimic.joint);parent_joint=articulation.find_joint_by_name(mimic.mimic);m=mimic.multiplier
    if joint.parent_link==parent_joint.child_link:
     if joint.parent_link.parent is None:raise RuntimeError('UNSUPPORTED_MIMIC_TOPOLOGY')
     articulation.create_fixed_tendon([joint.parent_link.parent,joint.parent_link,joint.child_link],[0,-m,1],[0,-1/m,1],rest_length=mimic.offset,stiffness=1e5,damping=5.)
    elif joint.parent_link==parent_joint.parent_link:
     articulation.create_fixed_tendon([joint.parent_link,joint.child_link,parent_joint.child_link],[0,-m,1],[0,-1/m,1],rest_length=mimic.offset,stiffness=1e5,damping=5.)
    else:raise RuntimeError('UNSUPPORTED_MIMIC_TOPOLOGY')
  for link in links:self.scene.add_entity(link)
  return articulation
 ArticulationBuilder.build=build
 try:yield
 finally:ArticulationBuilder.build=original
