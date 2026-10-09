"""Conservative generic task-evidence boundary; NO semantic identity oracle."""
import math
import numpy as np
from sim_skills.full_pnp.dependencies import angle

class TaskEvidenceAdapter:
    version='astra.task_evidence.v1'
    @staticmethod
    def check(binding, reference, current, actions, expected_state):
        out={'version':TaskEvidenceAdapter.version,'task_binding':binding,'status':'unknown',
             'identity_verified':False,'reason':'NO_EQUIVALENT_GENERIC_IDENTITY_AND_GOAL_VERIFIER'}
        if current['scene_healthy'] is not True: return dict(out,reason='SCENE_HEALTH_UNKNOWN')
        s=current['robot_state']
        if math.dist(s['actual_grasp_center_world'],expected_state['actual_grasp_center_world'])>=.01 or angle(s['flange_pose_world'][3:],expected_state['flange_pose_world'][3:])>=.05:
            return dict(out,status='invalid',reason='MEASURED_JOIN_CHANGED')
        if binding=={'profile':'scene_only_v1','object_id':'','goal_id':''}:
            return dict(out,status='valid' if all(a['type']=='hold' for a in actions) else 'unknown',reason='SCENE_ONLY_HOLD_NO_OBJECT_CLAIM')
        if binding!={'profile':'legacy_red_green_v1','object_id':'red_task_object','goal_id':'green_goal'}:
            return out
        if reference['backend']!='legacy_rgb_rays_v1' or current['backend']!='legacy_rgb_rays_v1':return out
        # This is ONLY the existing declared single-red task scope, not a multi-object mapping.
        for identity in ('red_task_object','green_goal'):
            before=reference['entities'].get(identity,{});after=current['entities'].get(identity,{})
            if before.get('status')!='coarse' or after.get('status')!='coarse':return dict(out,reason='CURRENT_GEOMETRY_UNKNOWN')
            p=np.array(before['point_world_m']);q=np.array(after['point_world_m'])
            if identity=='red_task_object':
                tool=np.array(reference['robot_state']['actual_grasp_center_world']);newtool=np.array(s['actual_grasp_center_world'])
                if np.linalg.norm(p-tool)<=.06:p=p-tool;q=q-newtool
            if np.linalg.norm(q-p)>.03:return dict(out,status='invalid',reason='ANCHOR_CHANGED_BEYOND_30MM')
        return dict(out,status='valid',reason='LEGACY_DECLARED_SCOPE_PLUS_COARSE_CHECK; ORIGINAL_OWNER_GATES_STILL_REQUIRED')
