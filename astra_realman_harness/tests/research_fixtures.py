"""TEST ONLY: static archived public RGB and fake execution, never a policy fallback."""
import copy
import json
import time
from pathlib import Path
from platform_v1.owner import Owner

FIXTURE=Path(__file__).parent/'fixtures/research_public_rgb'

class FakeScene:
    def __init__(self,backend):self.backend=backend;self.step_hook=None;self.inject=None
    def state(self):return copy.deepcopy(self.backend.state)
    def tick(self,n):
        for _ in range(n):
            if self.inject:self.inject()
            if self.step_hook:self.step_hook('before_step')
            self.backend.steps+=1;self.backend.state['sim_step']=self.backend.steps
            if self.step_hook:self.step_hook('after_step')

class FakeBackend:
    def __init__(self,assets,output,seed,video):
        output.mkdir(parents=True);self.output=output;self.steps=0;self.dt=.004;self.stopped=False
        self.template=json.loads((FIXTURE/'observation.json').read_text());self.state=copy.deepcopy(self.template['state'])
        self.state.update(sim_step=0,stopped=False);self.s=FakeScene(self);self.private_step_hook=lambda _:None
        self.counter=0;self.commands=[];self.failure=None
        (output/'TEST_ONLY.json').write_text(json.dumps({'source':'FAKE_EXECUTOR_STATIC_PUBLIC_RGB','physics_runs':0,'hardware_calls':0}))
    def observe(self):
        self.counter+=1;return {'observation_id':'test:%04d'%self.counter,'state':self.s.state(),
            'captured_monotonic':time.monotonic(),'capture_span_s':0.,'calibration':copy.deepcopy(self.template['calibration']),
            'images':{c:str(FIXTURE/(c+'.png')) for c in ('assembly','fixed','wrist')}}
    def execute_chunk(self,actions,ticket,current):
        assert ticket['owner_admitted'] and ticket['commit_observation_id']==current['observation_id']
        self.commands.append({'actions':copy.deepcopy(actions),'source_observation_id':current['observation_id'],'start':time.monotonic()})
        results=[]
        for i,a in enumerate(actions):
            if self.failure=='unknown' and i==1:raise RuntimeError('TEST_EXCEPTION_AFTER_PREFIX')
            if (self.failure=='partial' and i==1) or (self.failure=='first' and i==0):
                results.append({'action':a,'result':{'ok':False,'error':'STOPPED'}});break
            self.s.tick(round(a.get('seconds',.008)/self.dt))
            if a['type']=='move_pose':self.state['actual_grasp_center_world']=a['pose'][:3]
            results.append({'action':a,'result':{'ok':True,'after':self.s.state()}})
        self.commands[-1]['end']=time.monotonic()
        return {'ok':all(r['result']['ok'] for r in results),'results':results,'unexecuted_count':len(actions)-len(results)}
    def stop(self):self.stopped=True;self.state['stopped']=True
    def finish(self,verdict):return {'status':'FAIL','source':'FAKE_EXECUTOR_NO_PHYSICS_SCORE'}
    def close(self):pass

def owner(root,config=None,cap=20,source='RESEARCH_PROGRAM'):
    root.mkdir();o=Owner(None,root,budget_s=120,source=source,infer_config=config,max_requests=cap,backend_factory=FakeBackend)
    o.enable_research_adapters();return o

def wait_job(component,identity,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        row=component.poll(identity)
        if row['status'] in ('READY','FAILED','CANCELLED'):return row
        time.sleep(.01)
    raise AssertionError('OFFLINE_WORKER_DID_NOT_RETURN')

def initial_world(o):
    obs=o.observe();a=o.research
    request=a.world.submit([obs['observation_id']],[],'legacy_rgb_rays_v1')
    row=wait_job(a.world,request['request_id']);assert row['status']=='READY',row
    return obs,row['result']

def plan(obs,world,actions=None,H=8):
    return {'version':'astra.action_chunk_plan.v1','H':H,
        'waypoints':actions or [{'type':'hold','seconds':.02} for _ in range(H)],
        'world_id':world['world_id'],'world_revision':world['world_revision'],
        'source_observation_id':obs['observation_id'],'execution_epoch':obs['execution_epoch'],
        'task_binding':{'profile':'scene_only_v1','object_id':'','goal_id':''},
        'semantics':'PREDICTED_WAYPOINTS_NOT_MEASURED'}

def step(o,p):
    sup=o.research.supervisor;r=sup.step(p['plan_id'])
    if r['status']=='WAITING_WORLD':
        row=sup.plans[p['plan_id']];wait_job(o.research.world,row['world_job'])
        r=sup.step(p['plan_id'])
    return r
