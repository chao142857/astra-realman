"""Predetermined simulation event; private qualification is not policy input."""
import json,hashlib
from pathlib import Path
import numpy as np
from PIL import Image

class OcclusionEvent:
    def __init__(self,owner,out,config):
        self.owner=owner;self.scene=owner.b.s;self.out=Path(out)/'episode/private/occlusion_condition';self.out.mkdir()
        self.cfg=json.loads(Path(config).read_text());self.board=None;self.triggered=False;self.completed=False
        self.record={'config':self.cfg,'config_sha256':hashlib.sha256(Path(config).read_bytes()).hexdigest(),
                     'condition_valid':None,'triggered':False,'decisions_with_panel':0,'policy_input_events':0}
        self.save()
    def save(self):
        (self.out/'CONDITION.json').write_text(json.dumps(self.record,indent=2))
    def sample(self,label):
        # Independent condition scorer only. No masks/IDs/counts enter observations, WH, or prompts.
        s=self.scene;s.cameras['wrist'].set_pose(s.links['ctag_base_link'].get_pose()*s.wrist_relative)
        s.scene.update_render();counts={}
        for name,cam in s.cameras.items():
            cam.take_picture();rgb=(np.clip(cam.get_picture('Color')[:,:,:3],0,1)*255).astype(np.uint8)
            mask=np.asarray(cam.get_picture('Segmentation'))[:,:,1]==s.cube.per_scene_id
            counts[name]=int(mask.sum())
            Image.fromarray(rgb).save(self.out/(label+'_'+name+'.png'))
            Image.fromarray(mask.astype(np.uint8)*255).save(self.out/(label+'_'+name+'_PRIVATE_TARGET_MASK.png'))
        return counts
    def clear_collision(self):
        w=self.scene.motion.planning_world;w.update_from_simulation()
        from sapien.physx import PhysxRigidBaseComponent
        from mplib.collision_detection.fcl import collide
        # Compare current physical geometry even when the payload is FCL-attached.
        board=w.convert_physx_component(self.board.find_component_by_type(PhysxRigidBaseComponent))
        target=w.convert_physx_component(self.scene.cube.find_component_by_type(PhysxRigidBaseComponent))
        return not w.check_collision_between(self.board,self.scene.robot) and not collide(board,target).is_collision()
    def insert_after_chunk(self,phase,index,length,feedback):
        if self.triggered or phase!='transport' or index!=length or not feedback['ok']:return
        import sapien
        from sapien.physx import PhysxRigidBaseComponent
        from mplib.sapien_utils.conversion import convert_object_name
        self.triggered=True;before=self.sample('before');step=self.scene.step
        b=self.scene.scene.create_actor_builder()
        b.add_box_collision(half_size=self.cfg['half_size_local_xyz_m'],material=self.scene.material)
        b.add_box_visual(half_size=self.cfg['half_size_local_xyz_m'],material=self.cfg['color'])
        self.board=b.build_static(name='predetermined_occlusion_panel')
        pose=self.cfg['pose_world_xyz_wxyz'];self.board.set_pose(sapien.Pose(pose[:3],pose[3:]))
        w=self.scene.motion.planning_world
        w.add_object(w.convert_physx_component(self.board.find_component_by_type(PhysxRigidBaseComponent)))
        self.board_name=convert_object_name(self.board)
        after=self.sample('occluded');clear=self.clear_collision()
        valid=(before['fixed']>=self.cfg['minimum_pre_target_pixels'] and before['assembly']>=self.cfg['minimum_pre_target_pixels']
            and after['fixed']<=before['fixed']*self.cfg['fixed_target_visible_fraction_max']
            and after['assembly']>=max(self.cfg['minimum_assembly_post_pixels'],before['assembly']*self.cfg['assembly_target_visible_fraction_min']) and clear)
        self.record.update(triggered=True,inserted_step=step,phase=phase,chunk_length=length,
            before_target_pixels=before,occluded_target_pixels=after,collision_free_at_insertion=clear,
            actual_board_pose=[*map(float,self.board.pose.p),*map(float,self.board.pose.q)],condition_valid=bool(valid),
            held_physics_state_not_reinitialized=True)
        self.save();self.scene.capture_video_frame()
        if not valid:raise RuntimeError('OCCLUSION_CONDITION_INVALID_NO_RETUNE')
    def after_decision(self):
        if self.board is None or self.completed:return
        clear=self.clear_collision();self.record['decisions_with_panel']+=1
        if not clear:
            self.record.update(condition_valid=False,reason='PANEL_PHYSICAL_INTERFERENCE');self.save()
            raise RuntimeError('OCCLUSION_CONDITION_INVALID_PHYSICAL_INTERFERENCE')
        self.scene.motion.planning_world.remove_object(self.board_name)
        self.scene.scene.remove_actor(self.board);self.board=None;self.completed=True
        after=self.sample('removed');before=self.record['before_target_pixels']
        restored=after['fixed']>=.8*before['fixed']
        self.record.update(removed_step=self.scene.step,removed_before_next_motion=True,
            after_removal_target_pixels=after,visibility_restored=bool(restored),condition_valid=bool(restored))
        self.save();self.scene.capture_video_frame()
        if not restored:raise RuntimeError('OCCLUSION_CONDITION_INVALID_VISIBILITY_NOT_RESTORED')
