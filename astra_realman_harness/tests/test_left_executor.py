import copy,json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json
from left_terminal import select_replay
from left_executor import RealLeftExecutor
from exact_target_feasibility import check_exact_target

class Stop:
    value=False
    def is_set(self):return self.value
    def wait(self,_):return self.value
class Robot:
    def __init__(self,ret=0):self.calls=[];self.ret=ret
    def rm_algo_inverse_kinematics(self,params):return (0,[0]*6)
    def rm_movej_p(self,*args):self.calls.append(args);return self.ret
class Grip:
    calls=[];reply={'command':'hand_follow_pos','set_state':True}
    def __init__(self):self.last_result=None
    def set_gripper(self,arm,value):
        self.calls.append((arm,value));self.last_result={'command_return':self.reply,'send_attempts':1};return self.last_result
    def close(self):pass

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='left-executor-test-');self.step=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        src=read_json(ROOT/'logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json')
        self.obs=select_replay(src,read_json(ROOT/'config/left_terminal.json'),'task',None)
        self.obs['captured_at']=time.time();self.obs['canonical_states']['left']['timestamp']=time.time()
        for c in self.obs['cameras']:c['captured_at']=time.time()
        self.a=read_json(ROOT/'tests/left_opening_fixture.json');self.robot=Robot();self.stop=Stop();self.stop.value=False
        Grip.calls=[];Grip.reply={'command':'hand_follow_pos','set_state':True}
        self.captures=[]
        def capture(path):self.captures.append(path);return copy.deepcopy(self.obs)
        self.ex=RealLeftExecutor(SimpleNamespace(connected={'left':self.robot},sdk=SimpleNamespace(rm_inverse_kinematics_params_t=lambda **kw:kw)),capture,self.stop,self.step,Grip)
    def test_exact_two_channels(self):
        r=self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        b=self.obs['canonical_states']['left']['ee_pose']
        self.assertEqual(self.robot.calls,[([p+d for p,d in zip(b['xyz_m']+b['rpy_rad'],self.a['translation_m']+self.a['rotation_rpy_rad'])],1,0,0,1)])
        self.assertEqual(Grip.calls,[('left',.42)]);self.assertEqual(r['hardware_commands_sent'],2)
        self.assertTrue((self.step/'arm-dispatch.claim.json').exists());self.assertTrue((self.step/'gripper-dispatch.claim.json').exists())
    def test_arm_failure_no_gripper_no_retry(self):
        self.robot.ret=4099
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertEqual(len(self.robot.calls),1);self.assertFalse(Grip.calls)
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertEqual(len(self.robot.calls),1)
        self.assertEqual(read_json(self.step/'execution_result.json')['status'],'STOPPED')
    def test_gripper_failure_no_retry(self):
        Grip.reply={'command':'hand_follow_pos','set_state':False};self.a['translation_m']=[0,0,0]
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertEqual(Grip.calls,[('left',.42)]);self.assertFalse(self.robot.calls)
    def test_stop_before_dispatch(self):
        self.stop.value=True
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertFalse(self.robot.calls);self.assertFalse(Grip.calls)
    def test_stop_between_channels(self):
        def cap(path):self.stop.value=True;return self.obs
        self.ex.capture=cap
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertEqual(len(self.robot.calls),1);self.assertFalse(Grip.calls)
    def test_error_blocks(self):
        self.obs['canonical_states']['left']['system_error']['codes']=[4099]
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertFalse(self.robot.calls);self.assertFalse(Grip.calls)
    def test_stale_blocks(self):
        self.obs['canonical_states']['left']['timestamp']-=10
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertFalse(self.robot.calls)
    def test_done_no_commands(self):
        self.a.update(done=True,translation_m=[0,0,0]);r=self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertEqual(r['hardware_commands_sent'],0);self.assertFalse(Grip.calls)
    def test_satisfied_no_resend(self):
        self.a.update(translation_m=[0,0,0],gripper_opening=1)
        self.obs['canonical_states']['left']['gripper_state']['raw']['speed']=[0]
        r=self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs));self.assertEqual(r['status'],'NOOP');self.assertFalse(Grip.calls)
    def test_right_session_rejected(self):
        self.ex.session.connected['right']=Robot()
        with self.assertRaises(RuntimeError):self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs))
        self.assertFalse(self.robot.calls)
    def test_numeric_zero_close(self):
        self.a.update(translation_m=[0,0,0],gripper_opening=0)
        self.ex.execute(self.a,self.obs,feasibility=check_exact_target(self.ex.session,self.a,self.obs));self.assertEqual(Grip.calls,[('left',0)])

if __name__=='__main__':unittest.main()
