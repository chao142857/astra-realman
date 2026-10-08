"""Offline contact/control semantics. No SDK, physics scene or model launch."""
import json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.grasp_control import ContactState,SharedGraspController,CONTACT_CONFIRM_STEPS
from sim_skills.full_pnp.protocol import Memory
from sim_skills.model import feedback_projection,state_projection
from sim_skills.full_pnp.grasp_assessment import assess_grasp

class FakeScene:
    def __init__(self,root,contact=lambda n:True):
        self.output=root;self.step=0;self.q=0.;self.target=0.;self.closed_by_original=0;self.contact=contact
        self.stopped=threading.Event();self.action_count=0;self.latches=0;self.holds=0;self.props=[];self.commands=[]
        self.cfg={'control':{'gripper_stiffness':20.,'gripper_damping':2.,'physics_timeout_s':20.,'contact_preload_rad':.005,'contact_hold_torque_Nm':.1},'scene':{'dt':.004}}
        self.master=0;self.robot=NS(get_qpos=lambda:np.array([self.q]))
        self.joints=[NS(name='master',set_drive_property=lambda *a,**kw:self.props.append((a,kw)),
                        set_drive_target=self.set_target,get_drive_target=lambda:[self.target])]
        self.tree=NS(find=lambda _:NS(get=lambda _:10))
    def set_target(self,value):self.target=value;self.commands.append(value)
    def state(self):return {'gripper_master_rad':self.q,'sim_step':self.step,'stopped':self.stopped.is_set()}
    def phase(self,*a,**kw):pass
    def log(self,*a):pass
    def monitor(self):
        if getattr(self,'fault',False):raise RuntimeError('PAD_CONTACT_PENETRATION')
    def bilateral_pad_contact(self):return self.contact(self.step)
    def tick(self,n):
        for _ in range(n):
            if self.stopped.is_set():raise RuntimeError('STOPPED')
            self.step+=1;self.q=self.target;self.monitor()
    def hold(self):self.holds+=1
    def gripper(self,opening):
        self.closed_by_original+=1
        if -.91*(1-opening)>=self.q:return {'ok':True,'opening':opening}
        count=0;latched=None
        for _ in range(350):
            self.tick(1);count=count+1 if self.bilateral_pad_contact() else 0
            if count>=2 and latched is None:latched=self.latch_grasp_contact()
        return {'ok':True,'opening':opening,'contact_latch':latched,'after':self.state()}
    def latch_grasp_contact(self):
        self.latches+=1;self.set_target(self.q-.005);return {'step':self.step,'target_rad':self.target}

class ContactTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
    def controller(self,contact=lambda n:True):
        s=FakeScene(self.root,contact);c=SharedGraspController(s);self.addCleanup(c.close);return s,c
    def test_original_gripper_called_once_with_exact_opening(self):
        s,c=self.controller();r=c.gripper(.45)
        self.assertEqual(s.closed_by_original,1);self.assertEqual(r['opening'],.45)
        self.assertEqual(s.step,350);self.assertEqual(s.props,[])
    def test_transient_contact_is_not_confirmed(self):
        s,c=self.controller(lambda n:5<=n<=8);r=c.gripper(0)
        self.assertFalse(r['ok']);self.assertEqual(r['error'],'GRASP_CONTACT_LOST_AFTER_LATCH')
        self.assertEqual(s.latches,1);self.assertTrue(s.stopped.is_set())
        rows=[json.loads(x) for x in (self.root/'grasp_execution_private.jsonl').read_text().splitlines()]
        end=next(x['data'] for x in rows if x['event']=='CLOSING_END')
        self.assertTrue(end['command_completed']);self.assertFalse(end['contact_qualified'])
    def test_no_contact_fails_without_retry_or_latch(self):
        s,c=self.controller(lambda n:False);r=c.gripper(0)
        self.assertEqual(r['error'],'GRASP_CONTACT_NOT_ESTABLISHED');self.assertEqual(s.latches,0)
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):c.gripper(0)
    def test_confirmed_contact_not_stable_holding_claim(self):
        s,c=self.controller();r=c.gripper(.45);self.assertTrue(r['ok']);self.assertTrue(c.contact.armed)
        text=(self.root/'grasp_execution_private.jsonl').read_text();self.assertIn('NOT_ESTABLISHED_BY_CLOSING',text)
        self.assertNotIn('holding',feedback_projection(r))
    def test_loss_window_stops_continuation_and_original_checks_first(self):
        s,c=self.controller();c.gripper(.45);s.contact=lambda n:False
        for _ in range(19):s.tick(1)
        with self.assertRaisesRegex(RuntimeError,'GRASP_CONTACT_LOST'):s.tick(1)
        s.fault=True
        with self.assertRaisesRegex(RuntimeError,'PAD_CONTACT_PENETRATION'):c.monitor()
    def test_open_and_noop_do_not_claim_grasp(self):
        s,c=self.controller();s.q=-.3
        c.gripper(1);self.assertEqual(s.closed_by_original,1);self.assertFalse(c.contact.armed)
        r=c.gripper(1-.3/.91);self.assertTrue(r['noop']);self.assertEqual(s.step,0)
    def test_stale_or_duplicate_contact_does_not_accumulate(self):
        c=ContactState();c.begin('CLOSING')
        for _ in range(100):c.sample(1,True)
        self.assertEqual(c.run,1);c.sample(100,True);self.assertEqual(c.run,1)
        for n in range(101,150):c.sample(n,True)
        self.assertTrue(c.closure_result(True)[0])
    def test_external_stop_and_safety_abort_remain_failures(self):
        s,c=self.controller();s.stopped.set()
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):c.gripper(0)
        s.stopped.clear();s.fault=True
        with self.assertRaisesRegex(RuntimeError,'PAD_CONTACT_PENETRATION'):c.gripper(0)
        self.assertTrue(s.stopped.is_set())
    def test_private_truth_not_in_feedback_projection(self):
        data={'ok':False,'error':'GRASP_CONTACT_LOST_AFTER_LATCH','contact_status':'SECRET_CONTACT','object_pose':[1,2,3],
              'grasp_execution_private':{'target_xy':'GT'},'after':{'sim_step':1,'contact_force':99}}
        p=feedback_projection(data);self.assertEqual(p,{'ok':False,'error':'GRASP_CONTACT_LOST_AFTER_LATCH','after':{'sim_step':1}})
    def test_stable_contact_on_table_is_not_holding(self):
        rows=[{'step':n,'closed':True,'bilateral_contact':True,'object_pose':[0,0,.025],'grasp_center':[0,0,.025]} for n in range(400)]
        r=assess_grasp(rows,.025,{'command_completed':True,'contact_qualified':True})
        self.assertEqual(r['status'],'CONTACT_CONFIRMED_HOLD_NOT_VERIFIED')
    def test_hold_requires_continuous_contacts_and_lift(self):
        rows=[{'step':n,'closed':True,'bilateral_contact':True,'object_pose':[0,0,.105],'grasp_center':[0,0,.105]} for n in range(300)]
        closure={'command_completed':True,'contact_qualified':True}
        self.assertEqual(assess_grasp(rows,.025,closure)['status'],'STABLE_HOLD_VERIFIED')
        rows[100]['bilateral_contact']=False
        self.assertFalse(assess_grasp(rows,.025,closure)['stable_hold_seen'])
        rows[100]['bilateral_contact']=True;rows[100]['step']+=2
        self.assertFalse(assess_grasp(rows,.025,closure)['stable_hold_seen'])
    def test_final_B_E_A_payload_excludes_private_contact_and_score(self):
        import hashlib
        from PIL import Image
        from sim_skills.full_pnp.protocol import wire_base
        from sim_skills.full_pnp.wire import existing_infer_payload
        obs={'observation_id':'o','state':{'sim_step':1,'contact_truth':'PRIVATE_SENTINEL','grasp_execution_assessment':'PRIVATE_SENTINEL'},
             'captured_monotonic':1.,'capture_span_s':.01,'calibration':{},'grasp_execution_private':'PRIVATE_SENTINEL'}
        memory=Memory();action={'type':'gripper','opening':.45}
        memory.complete('one',obs,obs,[action],{'ok':False,'results':[{'action':action,'result':{'ok':False,
            'error':'GRASP_CONTACT_LOST_AFTER_LATCH','contact_truth':'PRIVATE_SENTINEL','grasp_execution_assessment':'PRIVATE_SENTINEL'}}]},1.)
        Image.new('RGB',(2,2),'gray').save(self.root/'image.png');data=(self.root/'image.png').read_bytes()
        for role in ('B','E','A'):
            wire=wire_base(obs,{'history_cutoff':2.}, {'status':'failed'},[0,0,.1,0,1,0,0],memory,'B' if role=='B' else 'F',0,role)
            wire['attachments']=[{'id':'i','file':'image.png','sha256':hashlib.sha256(data).hexdigest()}]
            (self.root/'wire.json').write_text(json.dumps(wire))
            payload=existing_infer_payload(self.root)
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(payload));self.assertIn('GRASP_CONTACT_LOST_AFTER_LATCH',json.dumps(payload))

if __name__=='__main__':unittest.main(verbosity=2)
