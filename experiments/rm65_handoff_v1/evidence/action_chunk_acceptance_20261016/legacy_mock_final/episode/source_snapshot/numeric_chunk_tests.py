"""Offline semantics tests. Fake execution is labelled, not physical evidence."""
import copy,json,tempfile,unittest,threading
from pathlib import Path
import numpy as np
from numeric_action_chunk import *


def tcp(side,poses):return {'arm':side,'kind':'tcp','waypoints_world_wxyz':poses}
def grip(side,opening=1.,mode='position'):return {'arm':side,'kind':'gripper','opening_fraction':opening,'contact_mode':mode}
def chunk(actions,mode='sequential'):return {'done':False,'stages':[{'mode':mode,'observe_s':.5,'actions':actions}]}


class FakeArm:
    def __init__(self,p):self.pose=p;self.stopped=threading.Event()
    def state(self):return {'actual_grasp_center_world':self.pose[:3],'flange_pose_world':self.pose}


class FakeWorld:
    def __init__(self,output,reject_at=None,raise_at=None):
        self.output=output;self.steps=0;self.dt=.004;self.records=[];self.calls=[];self.reject_at=reject_at;self.raise_at=raise_at
        self.arms={s:FakeArm([.2 if s=='left' else .5,0,.2,0,1,0,0]) for s in ['left','right']}
    def tick(self,n):self.steps+=n
    def execute_group(self,commands):
        self.calls.append(copy.deepcopy(commands));i=len(self.calls)
        if i==self.raise_at:
            self.steps+=1
            for a in self.arms.values():a.stopped.set()
            raise RuntimeError('TEST_PHYSICAL_STOP')
        if i==self.reject_at:return {'ok':False,'executed':False,'reason':'IK_REJECTED_COLLISION:TEST'}
        residuals={}
        for s,c in commands.items():
            if 'pose' in c:self.arms[s].pose=c['pose'];residuals[s]={'position_error_m':0.,'rotation_error_rad':0.}
        self.steps+=1;self.records.append({'step':self.steps,'arms':{s:a.state() for s,a in self.arms.items()}})
        return {'ok':True,'executed':True,'goal_residuals':residuals}


class Semantics(unittest.TestCase):
    def test_segment_bounds_exact_endpoint_and_no_detour(self):
        a=[.2,0,.2,0,1,0,0];b=[.231,.017,.209,0,1,0,0]
        nodes=segment_nodes(a,b);self.assertEqual(nodes[-1],b)
        previous=a
        for p in nodes:
            self.assertLessEqual(np.linalg.norm(np.array(p[:3])-previous[:3]),.00500000001)
            self.assertLess(np.linalg.norm(np.cross(np.array(p[:3])-a[:3],np.array(b[:3])-a[:3])),1e-12)
            previous=p
    def test_rotation_and_opposite_quaternion(self):
        a=[.2,0,.2,1,0,0,0];q=np.roll(Rotation.from_euler('z',7,degrees=True).as_quat(),1).tolist();b=[.2,0,.2,*q]
        nodes=segment_nodes(a,b);self.assertEqual(nodes[-1],b);previous=a
        for p in nodes:
            self.assertLessEqual((rotations(previous).inv()*rotations(p)).magnitude(),MAX_ROTATION_RAD+1e-12);previous=p
        self.assertEqual(len(segment_nodes(a,[.2,0,.2,-1,0,0,0])),1)
    def test_order_parallel_and_unchanged_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d);a=[.21,0,.2,0,1,0,0];b=[.51,0,.2,0,1,0,0]
            value=chunk([tcp('left',[a]),tcp('right',[b])],'parallel');saved=copy.deepcopy(value)
            r=execute_chunk(w,value);self.assertTrue(r['ok']);self.assertEqual(value,saved)
            self.assertEqual(set(w.calls[0]),{'left','right'})
            self.assertEqual([c['left']['pose'] for c in w.calls if 'left' in c][-1],a)
            self.assertEqual([c['right']['pose'] for c in w.calls if 'right' in c][-1],b)
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d);execute_chunk(w,chunk([grip('left'),grip('right')]))
            self.assertEqual([list(c) for c in w.calls],[['left'],['right']])
    def test_user_waypoint_corner_is_preserved(self):
        a=[.21,0,.2,0,1,0,0];b=[.21,.01,.2,0,1,0,0]
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d);execute_chunk(w,chunk([tcp('left',[a,b])]))
            poses=[c['left']['pose'] for c in w.calls];self.assertIn(a,poses);self.assertEqual(poses[-1],b)
            self.assertFalse(any(p[0]<.21 and p[1]>0 for p in poses))
    def test_rejection_does_not_rewrite_or_retry(self):
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d,reject_at=1);r=execute_chunk(w,chunk([tcp('left',[[.21,0,.2,0,1,0,0]])]))
            self.assertEqual(len(w.calls),1);self.assertEqual(w.steps,0);self.assertEqual(r['execution_status'],'REJECTED_WITHOUT_MOTION')
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d,reject_at=2);r=execute_chunk(w,chunk([tcp('left',[[.22,0,.2,0,1,0,0]])]))
            self.assertEqual(len(w.calls),2);self.assertFalse(r['ok']);self.assertEqual(r['execution_status'],'PARTIAL_FAILED')
    def test_physical_exception_is_archived_and_propagated(self):
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d,raise_at=1)
            with self.assertRaisesRegex(RuntimeError,'TEST_PHYSICAL_STOP'):execute_chunk(w,chunk([grip('left')]))
            r=json.loads((Path(d)/'chunk_001/receipt.json').read_text());self.assertTrue(r['safety_stop']);self.assertFalse(r['ok'])
    def test_observe_only_has_no_injected_action(self):
        with tempfile.TemporaryDirectory() as d:
            w=FakeWorld(d);value=chunk([]);r=execute_chunk(w,value)
            self.assertTrue(r['ok']);self.assertEqual(w.calls,[]);self.assertEqual(w.steps,125)
    def test_invalid_contract_and_private_skill_are_rejected(self):
        values=[{'done':True,'stages':[{}]},chunk([grip('left'),grip('left')]),
            chunk([{'arm':'left','kind':'handoff'}]),chunk([tcp('left',[[.2,0,.2,0,2,0,0]])]),
            chunk([tcp('left',[[.2,0,0,0,1,0,0]])]),dict(chunk([grip('left')]),witness=[])]
        for v in values:
            with self.subTest(v=v),self.assertRaises((ValueError,jsonschema.ValidationError)):parse_chunk(json.dumps(v))
        with self.assertRaises(ValueError):parse_chunk('{"done":true,"done":false,"stages":[]}')
    def test_no_task_or_private_route_dependency(self):
        import ast
        tree=ast.parse(Path(__file__).with_name('numeric_action_chunk.py').read_text())
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(x and any(y in x for y in ('reference','task','repair','centering')) for x in imports))
    def test_context_gt_and_image_isolation(self):
        from chunk_handoff_task import context_from_observation,validate_context
        folder=Path(__file__).parent/'evidence/numeric_baseline_01/initial_observation'
        obs=json.loads((folder/'observation.json').read_text());obs['images']=[str(folder/(x+'.png')) for x in ['overhead','tabletop_front','left_wrist','right_wrist']]
        c,images=context_from_observation(obs,[])
        for field in ['object_pose','expert_trajectory','witness','bilateral_contact_at_end','latched']:
            bad=copy.deepcopy(c);bad['recent_history']=[{'proposal':{'done':True,'stages':[]},'receipt':{field:[]}}]
            with self.assertRaises(ValueError):validate_context(bad,images)
        bad=copy.deepcopy(c);bad['attachments'][0]['sha256']='wrong'
        with self.assertRaises(ValueError):validate_context(bad,images)
    def test_private_contact_stays_in_raw_not_feedback(self):
        raw={'ok':True,'gripper_execution':{'right':{'bilateral_contact_at_end':True,'latched':True,'servo_target_rad':-.4}}}
        clean=public_receipt(raw)
        self.assertEqual(clean['gripper_execution']['right'],{'servo_target_rad':-.4})
        self.assertTrue(raw['gripper_execution']['right']['bilateral_contact_at_end'])


if __name__=='__main__':unittest.main(verbosity=2)
