"""Symmetry tests only; SDK, arm, gripper, and camera all replaced with mocks."""
import copy, hashlib, importlib.util, json, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT
from realman_api2_readonly import canonical_state
from arm_stack import ArmStack, capture_states, model_input, ENDPOINTS
from left_executor import RealArmExecutor
from exact_target_feasibility import check_exact_target
from lab_gripper_adapter import LabGripperAdapter

class Stop:
    def is_set(self):return False
    def wait(self,_):return False

def canonical(arm):
    now=time.time();w={'name':'World','pose':[0.]*6,'payload':0.,'x':0.,'y':0.,'z':0.};t=dict(w,name='Arm_Tip')
    values={'state':{'joint':[1.,2.,3.,4.,5.,6.],'pose':[.2,.1,.4,.0,.1,.2],'err':{'err_len':1,'err':['0']}},'work_before':w,'work_after':w,'tool_before':t,'tool_after':t}
    sample={'calls':{k:{'return_code':0,'raw_return':[0,v],'finished_at':now} for k,v in values.items()}}
    s=canonical_state(arm,sample,connection={'ip':ENDPOINTS[arm][0],'port':8080})
    s['gripper_state']={'position':1000,'raw':{'pos':[1000],'speed':[0],'sys_state':0,'dof_err':[0],'current':[12]}}
    return s

class Robot:
    def __init__(self,state):self.state=state;self.ik=[];self.moves=[];self.ret=0;self.ik_ret=0
    def rm_algo_inverse_kinematics(self,params):self.ik.append(params);return self.ik_ret,[1.]*6
    def rm_movej_p(self,pose,*args):
        self.moves.append((pose,args))
        if self.ret==0:
            self.state['ee_pose']['xyz_m']=pose[:3];self.state['ee_pose']['rpy_rad']=pose[3:];self.state['raw_sdk_state']['pose']=pose[:]
        return self.ret
    def rm_get_rm_plus_state_info(self):return 0,copy.deepcopy(self.state['gripper_state']['raw'])

class Tests(unittest.TestCase):
    def setUp(self):
        (ROOT/'logs').mkdir(exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='arm-mirror-test-');self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        self.states={a:canonical(a) for a in ('left','right')}
        self.robots={a:Robot(s) for a,s in self.states.items()}
        self.session=NS(connected=self.robots,sdk=NS(rm_inverse_kinematics_params_t=lambda **kw:kw),snapshot=lambda arm:{'canonical':copy.deepcopy(self.states[arm])})
        self.grip_calls=[];test=self
        class Grip:
            last_result=None
            def set_gripper(self,arm,value):
                test.grip_calls.append((arm,value));test.states[arm]['gripper_state']['position']=int(value*1000)
                test.states[arm]['gripper_state']['raw']['pos']=[int(value*1000)]
                self.last_result={'command_return':{'command':'hand_follow_pos','set_state':True}};return self.last_result
            def close(self):pass
        self.Grip=Grip
    def capture(self,path):
        for s in self.states.values():s['timestamp']=time.time()
        return capture_states(self.session,path,task='same task')
    def adapter(self,arm='right',execute=True):return ArmStack(arm,self.session,self.capture,Stop(),self.root/arm,execute_enabled=execute,gripper_factory=self.Grip)
    def proposal(self,arm='right'):
        return {'action_type':'cartesian_delta','arm':arm,'frame':'realman:'+arm+':work:World','tool_frame':'realman:'+arm+':tool:Arm_Tip',
                'translation_m':[.001,-.002,.003],'rotation_rpy_rad':[.01,0,0],'gripper_opening':.42,'done':False}
    def test_right_exact_target_and_handle(self):
        a=self.proposal();original=copy.deepcopy(a);result=self.adapter().run(a,'one')
        self.assertEqual(result['status'],'EXECUTED');self.assertEqual(a,original)
        self.assertEqual(self.robots['right'].moves,[([.201,.098,.403,.01,.1,.2],(1,0,0,1))])
        self.assertEqual(self.grip_calls,[('right',.42)]);self.assertFalse(self.robots['left'].moves);self.assertFalse(self.robots['left'].ik)
    def test_left_mirror_same_call(self):
        self.adapter('left').run(self.proposal('left'),'one')
        self.assertEqual(self.robots['left'].moves,[([.201,.098,.403,.01,.1,.2],(1,0,0,1))]);self.assertEqual(self.grip_calls,[('left',.42)])
    def test_ik_exact_no_search_or_scaling(self):
        self.robots['right'].ik_ret=1;a=self.proposal();result=self.adapter().run(a,'one')
        self.assertEqual(result['status'],'REJECTED_IK');self.assertEqual(len(self.robots['right'].ik),1)
        self.assertEqual(self.robots['right'].ik[0]['q_pose'],[.201,.098,.403,.01,.1,.2]);self.assertFalse(self.robots['right'].moves);self.assertFalse(self.grip_calls)
    def test_ik_fault_not_unreachable(self):
        self.robots['right'].ik_ret=-2
        with self.assertRaises(RuntimeError):self.adapter().run(self.proposal(),'one')
        self.assertFalse(self.robots['right'].moves)
    def test_command_failure_no_gripper_no_retry(self):
        self.robots['right'].ret=1;adapter=self.adapter()
        with self.assertRaises(RuntimeError):adapter.run(self.proposal(),'one')
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):adapter.run(self.proposal(),'one')
        self.assertEqual(len(self.robots['right'].moves),1);self.assertFalse(self.grip_calls)
    def test_journal_persists_no_retry(self):
        self.adapter().run(self.proposal(),'one')
        with self.assertRaises(FileExistsError):self.adapter().run(self.proposal(),'one')
        self.assertEqual(len(self.robots['right'].moves),1)
    def test_after_gripper_error_stops(self):
        adapter=self.adapter()
        original=self.Grip.set_gripper
        def failed_readback(g,arm,value):
            ret=original(g,arm,value);self.states[arm]['gripper_state']['raw']['dof_err']=[1];return ret
        with patch.object(self.Grip,'set_gripper',failed_readback):
            with self.assertRaisesRegex(RuntimeError,'AFTER_STATE'):adapter.set_gripper(.5,'one')
        self.assertEqual(len(self.grip_calls),1)
    def test_frame_change_after_arm_blocks_gripper(self):
        robot=self.robots['right'];original=robot.rm_movej_p
        def changed(*args):
            ret=original(*args);self.states['right']['raw_tool_frame']['pose'][2]=.01;return ret
        robot.rm_movej_p=changed
        with self.assertRaisesRegex(RuntimeError,'TOOL_FRAME_CHANGED'):self.adapter().run(self.proposal(),'one')
        self.assertEqual(len(robot.moves),1);self.assertFalse(self.grip_calls)
    def test_dry_run_no_commands(self):
        result=self.adapter(execute=False).run(self.proposal(),'one');self.assertEqual(result['status'],'DRY_RUN_NOT_SENT')
        self.assertFalse(self.robots['right'].moves);self.assertFalse(self.grip_calls)
    def test_pose(self):
        s=self.states['right'];pose=[.25,.13,.45,.1,.2,.3]
        self.adapter().move_to_pose(pose,s['work_frame']['id'],s['tool_frame']['id'],'one')
        for x,y in zip(self.robots['right'].moves[0][0],pose):self.assertAlmostEqual(x,y)
    def test_gripper_does_not_move_arm(self):
        self.adapter().set_gripper(.7,'one');self.assertEqual(self.grip_calls,[('right',.7)]);self.assertFalse(self.robots['right'].moves);self.assertFalse(self.robots['right'].ik)
    def test_satisfied_gripper_not_resent(self):
        result=self.adapter().set_gripper(1.,'one');self.assertEqual(result['status'],'NOOP');self.assertFalse(self.grip_calls)
    def test_wrong_arm_blocked(self):
        with self.assertRaises(ValueError):self.adapter().run(self.proposal('left'),'one')
        self.assertFalse(self.robots['right'].moves)
    def test_unknown_frame_blocked(self):
        a=self.proposal();a['frame']='realman:left:work:World'
        with self.assertRaises(ValueError):self.adapter().run(a,'one')
        self.assertFalse(self.robots['right'].moves)
    def test_controller_frame_names_used(self):
        s=self.states['right'];s['work_frame']['name']='RightWorld';s['work_frame']['id']='realman:right:work:RightWorld';s['raw_work_frame']['name']='RightWorld'
        s['work_frame']['definition_fingerprint']=hashlib.sha256(json.dumps(s['raw_work_frame'],sort_keys=True).encode()).hexdigest()
        a=self.proposal();a['frame']=s['work_frame']['id'];self.adapter().run(a,'one');self.assertEqual(len(self.robots['right'].moves),1)
    def test_controller_error_stops(self):
        self.states['right']['system_error']['codes']=[4105]
        with self.assertRaisesRegex(RuntimeError,'ROBOT_ERROR'):self.adapter().run(self.proposal(),'one')
        self.assertFalse(self.robots['right'].moves)
    def test_other_connected_arm_error_stops(self):
        self.states['left']['system_error']['codes']=[4099]
        with self.assertRaises(RuntimeError):self.adapter().run(self.proposal(),'one')
        self.assertFalse(self.robots['right'].moves)
    def test_sdk_units_unchanged(self):
        obs=self.capture(self.root/'observation');self.assertEqual(obs['canonical_states']['right']['joint_deg'],[1.,2.,3.,4.,5.,6.]);self.assertEqual(obs['canonical_states']['right']['ee_pose']['xyz_m'],[.2,.1,.4])
    def test_symmetric_model_fields(self):
        context=model_input(self.capture(self.root/'observation'))
        for key in ('robot_states','work_frames','tool_frames'):self.assertEqual(set(context[key]),{'left','right'})
        self.assertEqual(set(context['robot_states']['left']),set(context['robot_states']['right']));self.assertEqual(context['task'],'same task')
        self.assertEqual(len(context['action_schema']['required']),8)
    def test_raw_feedback_and_after_separate(self):
        result=self.adapter().run(self.proposal(),'one');folder=Path(result['log'])
        for name in ('raw_proposal.json','parsed_action.json','feasibility.json','executed_action.json','sdk_result.json','after_state.json','arm-dispatch.claim.json','gripper-dispatch.claim.json'):self.assertTrue((folder/name).exists(),name)
        self.assertIn('current',result['after_state']['right']['gripper_state']['raw'])
    def test_stop_no_motion(self):
        adapter=self.adapter();adapter.stop=threading.Event();adapter.stop.set()
        with self.assertRaisesRegex(RuntimeError,'HUMAN_STOP'):adapter.run(self.proposal(),'one')
        self.assertFalse(self.robots['right'].moves)
    def test_done_no_commands(self):
        a=self.proposal();a.update(done=True,translation_m=[0,0,0],rotation_rpy_rad=[0,0,0]);result=self.adapter().run(a,'one')
        self.assertEqual(result['status'],'MODEL_DONE');self.assertFalse(self.grip_calls);self.assertFalse(self.robots['right'].moves)
    def test_bimanual_adapter_real_route(self):
        from bimanual_demo.executors import RealArmExecutor as FoundationExecutor
        ex=FoundationExecutor('right',self.session,self.capture,Stop(),self.root/'foundation',execute_enabled=True,gripper_factory=self.Grip)
        ex.move_delta([0,0,.002],[0,0,0],'realman:right:work:World','one')
        self.assertEqual(len(self.robots['right'].moves),1);self.assertFalse(self.robots['left'].moves)
    def test_original_gripper_constructor_config_and_wire(self):
        configs=[];sent=[]
        class Sock:
            def send(self,data):sent.append(json.loads(data));return len(data)
            def recv(self,n):return b'{"command":"hand_follow_pos","set_state":true}'
            def close(self):pass
        class Driver:
            def __init__(self,config):configs.append(config);self.arm_ip='192.168.1.18';self.arm_port=8080;self.arm=Sock()
            def set_gripper_position(self,value):self.arm.send(json.dumps({'command':'hand_follow_pos','hand_pos':[int(value*1000)]}).encode());self.arm.recv(1024)
        loader=NS(exec_module=lambda m:setattr(m,'RmArm',Driver));spec=NS(loader=loader)
        with patch('lab_gripper_adapter.importlib.util.spec_from_file_location',return_value=spec),patch('lab_gripper_adapter.importlib.util.module_from_spec',return_value=NS()):
            adapter=LabGripperAdapter('right');r=adapter.set_gripper('right',.3509)
            self.assertEqual(configs,['/home/tongji/aloha/RealMan_Control/config/rm_right_arm.yaml']);self.assertEqual(sent,[{'command':'hand_follow_pos','hand_pos':[350]}]);self.assertEqual(r['existing_argument'],.3509)
            with self.assertRaises(RuntimeError):adapter.set_gripper('right',.3509)
            adapter.close()

if __name__=='__main__':unittest.main()
