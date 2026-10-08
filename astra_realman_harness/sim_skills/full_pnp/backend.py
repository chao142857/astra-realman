"""Single-owner full-task adapter. Frozen legacy dispatch/payload/score, no service main."""
import hashlib
import json
from pathlib import Path
import threading
import time
import numpy as np
from scipy.spatial.transform import Rotation
from sim_skills.rm65 import RM65Backend
from sim_skills.model import state_projection


class FullTaskBackend(RM65Backend):
    decision_wait_mode='owner_wall_paced_hold_or_approved_motion'
    def __init__(self,assets,output,seed=2,video=False):
        self.owner=threading.get_ident()
        super().__init__(assets,output,seed,video)
        # Object-independent, empty-hand preparation only. No setup_held call.
        preparation=self.s.move_tcp([.30,0.,.15,0.,1.,0.,0.])
        if not preparation['ok']:raise RuntimeError('GENERIC_EMPTY_PREPARATION_FAILED')
        from sim_skills.full_pnp.legacy_model_bridge import ModelAdapter
        self.adapter=ModelAdapter(self.s)
        self.private_step_hook=self.s.step_hook
        self.commit_counter=0
        self.s.step_hook=None
        self.public_start=self.observe()
        self.provenance={'legacy_file_sha256':hashlib.sha256(Path(__file__).with_name('legacy_model_bridge.py').read_bytes()).hexdigest(),
                         'initialization':'generic empty-hand preparation; object-independent',
                         'setup_held_calls':0,'start_state':self.public_start['state']}
        (Path(output)/'full_task_adapter.json').write_text(json.dumps(self.provenance,indent=2))
    def assert_owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('SCENE_OWNER_ONLY')
    def setup_held(self):raise RuntimeError('SETUP_HELD_FORBIDDEN_FULL_TASK')
    def observe(self):
        self.assert_owner();start=time.monotonic()
        obs=super().observe()
        obs['state']=state_projection(obs['state'])
        obs['captured_monotonic']=time.monotonic()
        obs['capture_span_s']=obs['captured_monotonic']-start
        obs['calibration']={name:{'pose_world_xyz_wxyz':[*map(float,c.get_pose().p),*map(float,c.get_pose().q)],
            'intrinsic':c.get_intrinsic_matrix().tolist(),'resolution':[640,480],
            'axes':'SAPIEN +x forward,+y left,+z up'} for name,c in self.s.cameras.items()}
        return obs
    def execute_chunk(self,actions,ticket,commit_observation):
        self.assert_owner()
        if not ticket.get('owner_admitted'):raise RuntimeError('OWNER_TICKET_REQUIRED')
        if ticket['commit_observation_id']!=commit_observation['observation_id']:raise RuntimeError('COMMIT_OBSERVATION')
        self.commit_counter+=1
        # A new owner command references an ACTUAL commit observation. The model candidate
        # retains its original source observation, separately in ticket and immutable raw.
        request={'method':'chunk','observation_id':commit_observation['observation_id'],
                 'actions':actions,'reason':'OWNER_COMMIT:'+ticket['candidate_id']}
        path=self.s.output/('owner_commit_%03d.json'%self.commit_counter)
        path.write_text(json.dumps({'ticket':ticket,'executor_request':request},indent=2))
        return self.adapter.dispatch(request)
    def finish(self,verdict):
        self.assert_owner()
        result=self.adapter.finish('POLICY_CLOSED_BEFORE_PRIVATE_SCORE:'+verdict)
        # Independent exit geometry only; never goes to a worker or a target generator.
        p=self.s.cube.get_pose();R=Rotation.from_quat(np.roll(p.q,-1)).as_matrix()
        local=(self.s.pads()-np.asarray(p.p))@R
        half=self.s.cfg['scene']['cube_size_m']/2
        clearance=float(np.min(np.linalg.norm(np.maximum(np.abs(local)-half,0),axis=1)))
        state=self.s.state();exited=bool(state['actual_grasp_center_world'][2]>=.08 and clearance>=.03
                                     and not self.s.bilateral_pad_contact())
        physical=result['status']=='PASS' and exited
        result.update(legacy_status=result['status'],physical_success=physical,exited=exited,
                      pad_center_to_object_box_clearance_m=clearance,model_verdict=verdict,
                      strict_success=physical and verdict=='done',score_source='INDEPENDENT_SIMULATOR_TRUTH',
                      status='PASS' if physical and verdict=='done' else 'FAIL')
        (self.s.output/'full_task_score.json').write_text(json.dumps(result,indent=2))
        return result
    def close(self):
        if hasattr(self,'adapter'):
            self.adapter.records.close();self.adapter.private.close()
        super().close()
