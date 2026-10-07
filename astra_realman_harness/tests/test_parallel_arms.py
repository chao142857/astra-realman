"""Offline concurrency and failure tests. No model, SDK, sockets or hardware."""
import copy,json,sys,tempfile,threading,time,unittest,importlib.util
from types import SimpleNamespace as NS
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT
from parallel_arms import GroupCoordinator,parse_group,group_schema


def states():return {a:{'work_frame':{'id':'realman:'+a+':work:World'},'tool_frame':{'id':'realman:'+a+':tool:Arm_Tip'}} for a in ('left','right')}
def action(arm):return {'action_type':'cartesian_delta','arm':arm,'frame':'realman:'+arm+':work:World','tool_frame':'realman:'+arm+':tool:Arm_Tip','translation_m':[0,0,.001],'rotation_rpy_rad':[0,0,0],'gripper_opening':.5,'done':False}
def group(mode='parallel'):return {'done':False,'execution':mode,'actions':[action('left'),action('right')]}

class Worker:
    def __init__(self,arm,events,barrier=None):self.arm=arm;self.events=events;self.barrier=barrier;self.status='PASS_IK';self.fault=False;self.calls=0;self.refreshed=0
    def prepare(self,a,step):self.events.append(('prepare',self.arm));self.original=copy.deepcopy(a);return {'status':self.status}
    def refresh(self):self.refreshed+=1;return {'status':self.status}
    def execute(self):
        self.calls+=1;self.events.append(('start',self.arm))
        if self.barrier:self.barrier.wait(timeout=2)
        if self.fault:raise RuntimeError('SDK_COMMAND_ERROR')
        time.sleep(.01);self.events.append(('finish',self.arm));return {'status':'EXECUTED','hardware_commands_sent':1}

class Tests(unittest.TestCase):
    def setUp(self):
        (ROOT/'logs').mkdir(exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='parallel-test-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.events=[];self.stop=threading.Event();self.workers={a:Worker(a,self.events) for a in ('left','right')};self.c=GroupCoordinator(self.workers,self.stop)
    def test_worker_uses_own_session_and_refuses_second_dispatch(self):
        from arm_worker import worker_main
        spec=importlib.util.spec_from_file_location('mirror_fixture',ROOT/'tests/test_arm_mirror.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        state=helper.canonical('right');robot=helper.Robot(state);connections=[]
        class Session:
            def __init__(self,*args):self.connected={};self.sdk=NS(rm_inverse_kinematics_params_t=lambda **kw:kw)
            def __enter__(self):return self
            def __exit__(self,*args):connections.append('closed')
            def connect(self,arm,ip,port):connections.append((arm,ip,port));self.connected[arm]=robot;return {'connected':True}
            def snapshot(self,arm):state['timestamp']=time.time();return {'canonical':copy.deepcopy(state)}
        a=action('right');a['gripper_opening']=1
        requests=iter([{'kind':'prepare','action':a,'step':str(self.root/'command')},{'kind':'execute'},{'kind':'execute'},{'kind':'close'}]);responses=[]
        conn=NS(recv=lambda:next(requests),send=lambda value:responses.append(copy.deepcopy(value)),close=lambda:None)
        with patch.dict(sys.modules,{'realman_api2_readonly':NS(SDKReadOnly=Session)}):worker_main('right',conn,self.stop,self.root/'worker')
        self.assertEqual(connections,[('right','192.168.1.18',8080),'closed']);self.assertEqual(len(robot.moves),1)
        self.assertEqual(responses[1]['value']['status'],'PASS_IK');self.assertEqual(responses[2]['value']['status'],'EXECUTED')
        self.assertFalse(responses[3]['ok']);self.assertIn('ALREADY_USED',responses[3]['error'])
    def test_parallel_really_overlaps(self):
        barrier=threading.Barrier(2)
        for w in self.workers.values():w.barrier=barrier
        self.assertEqual(self.c.run(group(),self.root,execute=True)['status'],'COMPLETED')
        self.assertEqual([x[0] for x in self.events],['prepare','prepare','start','start','finish','finish'])
    def test_sequential_and_refresh(self):
        self.c.run(group('sequential'),self.root,execute=True)
        self.assertEqual(self.events,[('prepare','left'),('prepare','right'),('start','left'),('finish','left'),('start','right'),('finish','right')]);self.assertEqual(self.workers['right'].refreshed,1)
    def test_no_dispatch_if_either_ik_rejects(self):
        self.workers['right'].status='REJECTED_IK';r=self.c.run(group(),self.root,execute=True)
        self.assertEqual(r['status'],'REJECTED_IK');self.assertEqual(sum(w.calls for w in self.workers.values()),0);self.assertFalse(self.stop.is_set())
    def test_check_fault_stops(self):
        self.workers['right'].status='CHECK_ERROR'
        with self.assertRaisesRegex(RuntimeError,'GROUP_CHECK_FAULT'):self.c.run(group(),self.root,execute=True)
        self.assertEqual(sum(w.calls for w in self.workers.values()),0);self.assertTrue(self.stop.is_set())
    def test_fault_collects_both_results_no_retry(self):
        self.workers['left'].fault=True
        with self.assertRaises(RuntimeError):self.c.run(group(),self.root,execute=True)
        r=json.loads((self.root/'group_result.json').read_text());self.assertEqual(set(r['arms']),{'left','right'})
        self.assertEqual(r['arms']['left']['status'],'FAULT');self.assertTrue(self.stop.is_set())
        self.assertLessEqual(max(w.calls for w in self.workers.values()),1)
    def test_shadow_no_execution(self):
        r=self.c.run(group(),self.root);self.assertEqual(r['status'],'SHADOW_ONLY');self.assertEqual(sum(w.calls for w in self.workers.values()),0)
    def test_done_no_preflight(self):
        r=self.c.run({'done':True,'execution':'parallel','actions':[]},self.root,execute=True);self.assertEqual(r['status'],'MODEL_DONE');self.assertEqual(self.events,[])
    def test_omitted_arm_holds(self):
        g=group();g['actions']=g['actions'][:1];r=self.c.run(g,self.root,execute=True)
        self.assertEqual(r['held_arms'],['right']);self.assertEqual(self.workers['right'].calls,0)
    def test_stop_before_dispatch(self):
        self.stop.set()
        with self.assertRaisesRegex(RuntimeError,'HUMAN_STOP'):self.c.run(group(),self.root,execute=True)
        self.assertEqual(self.events,[])
    def test_no_group_retry(self):
        self.c.run(group(),self.root,execute=True)
        with self.assertRaisesRegex(RuntimeError,'CONSUMED'):self.c.run(group(),self.root,execute=True)
        self.assertEqual(sum(w.calls for w in self.workers.values()),2)
    def test_duplicate_arm_rejected(self):
        g=group();g['actions'][1]=action('left')
        with self.assertRaises(ValueError):parse_group(g,states())
    def test_cross_arm_frame_rejected(self):
        g=group();g['actions'][0]['frame']='realman:right:work:World'
        with self.assertRaises(ValueError):parse_group(g,states())
    def test_nan_rejected(self):
        g=group();g['actions'][0]['translation_m'][0]=float('nan')
        with self.assertRaises(ValueError):parse_group(g,states())
    def test_original_values_preserved(self):
        g=group();original=copy.deepcopy(g);self.c.run(parse_group(g,states()),self.root,execute=True)
        self.assertEqual(g,original)
        for a in g['actions']:self.assertEqual(self.workers[a['arm']].original,a)
    def test_done_with_action_rejected(self):
        g=group();g['done']=True
        with self.assertRaises(ValueError):parse_group(g,states())
    def test_one_model_schema_same_eight_field_children(self):
        schema=group_schema(states());self.assertEqual(len(schema['properties']['actions']['items']['required']),8);self.assertEqual(schema['properties']['actions']['maxItems'],2)
    def test_no_child_terminal_action(self):
        g=group();g['actions'][0].update(done=True,translation_m=[0,0,0])
        with self.assertRaises(ValueError):parse_group(g,states())

if __name__=='__main__':unittest.main()
