"""Protocol test double. No physics, perception, or task-success credit."""
import copy
from pathlib import Path
import threading
from bimanual_demo.evidence import PNG


class FixtureBackend:
    source='PROTOCOL_TEST_DOUBLE_NOT_PHYSICS'
    dt=.004
    def __init__(self,output):
        self.root=Path(output);self.root.mkdir(parents=True,exist_ok=False)
        self.s=self;self.step_hook=None;self.step=0;self.count=0;self.halted=False
        self.owner=threading.get_ident();self.pose=[.32,.02,.12,0,1,0,0];self.calls=[]
    @property
    def steps(self):return self.step
    @property
    def stopped(self):return self.halted
    def assert_owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('SCENE_OWNER_ONLY')
    def tick(self,n):
        self.assert_owner()
        for _ in range(n):
            if self.halted:raise RuntimeError('STOPPED')
            if self.step_hook:self.step_hook('before_step')
            self.step+=1
            if self.step_hook:self.step_hook('after_step')
    def state(self):
        self.assert_owner()
        return {'sim_step':self.step,'actual_grasp_center_world':self.pose[:3],
                'flange_pose_world':list(self.pose),'stopped':self.halted,
                'private_object_truth':'MUST_NOT_REACH_SNAPSHOT','contact_truth':True,'final_score':'PRIVATE'}
    def observe(self):
        self.assert_owner();self.count+=1;folder=self.root/('obs-%03d'%self.count);folder.mkdir()
        images={}
        for camera in ('assembly','fixed','wrist'):
            path=folder/(camera+'.png');path.write_bytes(PNG);images[camera]=str(path)
        return {'observation_id':'fixture-%03d'%self.count,'images':images,'state':self.state(),
                'frame':'sapien:world','pose_convention':'pad centre xyz metres; Link6 wxyz'}
    def setup_held(self):return {'source':self.source,'exact_clone':False,'policy_grasp_credit':False}
    def check(self,primitive):return {'ok':not self.halted,'source':self.source}
    def execute(self,primitive):
        self.assert_owner();self.tick(180 if primitive['name']=='approach' else 10)
        if 'target' in primitive:self.pose=copy.deepcopy(primitive['target'])
        self.calls.append(primitive);return {'ok':True,'source':self.source}
    def evaluate(self):return {'status':'PASS','source':self.source,'physical_score':None}
    def stop(self):self.halted=True
    def close(self):pass
