import copy,io,json,sys,tempfile,time,unittest,importlib.util,types
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json
from left_terminal import select_replay,command_plan,model_input,SCHEMA_PATH
from exact_target_feasibility import check_exact_target,dispatch_checked,require_exact_check,FeasibilityFault

class Checks(unittest.TestCase):
 def setUp(self):
  src=read_json(ROOT/'logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json')
  self.obs=select_replay(src,read_json(ROOT/'config/left_terminal.json'),'task',None)
  self.action=read_json(ROOT/'tests/left_opening_fixture.json');self.calls=[];self.ret=(0,[1,2,3,4,5,6])
  def ik(params):self.calls.append(params);return self.ret
  self.session=types.SimpleNamespace(connected={'left':types.SimpleNamespace(rm_algo_inverse_kinematics=ik)},sdk=types.SimpleNamespace(rm_inverse_kinematics_params_t=lambda **k:k))
 def test_exact_target_once(self):
  before=copy.deepcopy(self.action);c=check_exact_target(self.session,self.action,self.obs)
  self.assertEqual(c['status'],'PASS_IK');self.assertEqual(len(self.calls),1)
  self.assertEqual(self.calls[0]['q_pose'],command_plan(self.action,self.obs['canonical_states']['left'])['arm']['pose'])
  self.assertEqual(self.calls[0]['flag'],1);self.assertEqual(self.action,before)
 def test_reject_never_constructs_executor_or_moves_gripper(self):
  self.ret=(1,[0]*6);c=check_exact_target(self.session,self.action,self.obs)
  r=dispatch_checked(self.action,self.obs,c,lambda:self.fail('executor constructed'))
  self.assertEqual(r['status'],'REJECTED_IK');self.assertEqual(r['hardware_commands_sent'],0)
  self.assertEqual(r['executed_action'],{'arm':None,'gripper':None})
 def test_api_fault_not_rejection(self):
  for value in (-1,-2,-3,7,True):
   self.ret=(value,[0]*6);c=check_exact_target(self.session,self.action,self.obs)
   self.assertEqual(c['status'],'CHECK_ERROR')
   with self.assertRaises(FeasibilityFault):dispatch_checked(self.action,self.obs,c,lambda:self.fail('executor constructed'))
 def test_invalid_solution_fault(self):
  self.ret=(0,[float('nan')]*6);self.assertEqual(check_exact_target(self.session,self.action,self.obs)['status'],'CHECK_ERROR')
 def test_no_motion_no_ik(self):
  self.action['translation_m']=[0,0,0];c=check_exact_target(self.session,self.action,self.obs)
  self.assertEqual(c['status'],'NOT_REQUIRED');self.assertFalse(self.calls)
 def test_changed_target_cannot_reuse_check(self):
  c=check_exact_target(self.session,self.action,self.obs);self.action['translation_m'][0]+=.01
  with self.assertRaises(FeasibilityFault):require_exact_check(c,self.action,self.obs)
 def test_changed_state_cannot_reuse_check(self):
  c=check_exact_target(self.session,self.action,self.obs);self.obs['canonical_states']['left']['ee_pose']['xyz_m'][0]+=.01
  with self.assertRaises(FeasibilityFault):require_exact_check(c,self.action,self.obs)

class LoopTests(unittest.TestCase):
 def run_loop(self,entry,ik_fault=False,command_fault=False):
  spec=importlib.util.spec_from_file_location('tested_left_runner',ROOT/'scripts'/entry);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
  source=read_json(ROOT/'logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json')
  state=copy.deepcopy(source['canonical_states']['left']);motions=[];contexts=[]
  class Robot:
   def rm_get_rm_plus_state_info(self):return (0,copy.deepcopy(state['gripper_state']['raw']))
   def rm_algo_inverse_kinematics(self,params):
    if ik_fault:return (-2,[0]*6)
    # First original target explicitly rejected; subsequent original target succeeds.
    return (1,[0]*6) if len(contexts)==1 else (0,list(state['joint_deg']))
   def rm_movej_p(self,pose,*args):
    motions.append(list(pose))
    if command_fault:return 1
    state['ee_pose']['xyz_m']=pose[:3];state['ee_pose']['rpy_rad']=pose[3:];state['raw_sdk_state']['pose']=list(pose)
    return 0
  class Session:
   def __init__(self,*args):self.connected={};self.sdk=types.SimpleNamespace(rm_inverse_kinematics_params_t=lambda **k:k)
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def connect(self,arm,host,port):
    assert arm=='left' and host=='192.168.1.19';self.connected[arm]=Robot();return {'connected':True}
   def snapshot(self,arm):
    assert arm=='left';s=copy.deepcopy(state);s['timestamp']=time.time();return {'canonical':s}
  class Cameras:
   def __init__(self,c):self.configs=c
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def snapshot(self,path):
    images=[];by={c['serial']:c for c in source['cameras']}
    for c in self.configs:
     image=copy.deepcopy(by[c['serial']]);image.update(role=c['role'],role_confirmed=c['role_confirmed'],captured_at=time.time());images.append(image)
    return images,[],{'capture_span_ms':1}
  first=read_json(ROOT/'tests/left_opening_fixture.json')
  second=dict(first,translation_m=[.001,0,0],gripper_opening=1)
  done=dict(second,translation_m=[0,0,0],done=True)
  actions=[first,second,done]
  def astra(context,run,*args):
   contexts.append(copy.deepcopy(context));raw=json.dumps(actions[len(contexts)-1]);(run/'astra_raw.txt').write_text(raw);return raw
  fake_modules={'camera_session':types.SimpleNamespace(CameraSession=Cameras),'realman_api2_readonly':types.SimpleNamespace(SDKReadOnly=Session)}
  with tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='feasibility-loop-test-') as folder:
   counter=[0]
   def new(path):
    path=Path(path)
    if path.parent==ROOT/'logs':path=Path(folder)/'run'
    path.mkdir(parents=True,exist_ok=False);return path
   with patch.dict(sys.modules,fake_modules),patch.object(runner,'new_run',new),patch.object(runner,'call_astra',astra),patch.object(runner.signal,'signal'),patch.object(sys,'stdin',io.StringIO('')),patch.object(sys,'argv',[entry,'--live','--execute','--task','unchanged task','--max-steps','3','--no-preview']),redirect_stdout(io.StringIO()):
    code=runner.main()
   run=Path(folder)/'run';summary=read_json(run/'summary.json')
   if ik_fault:
    self.assertEqual(code,1);self.assertEqual(len(contexts),1);self.assertFalse(motions)
    self.assertIn('FEASIBILITY_CHECK_FAULT',summary['reason']);return
   self.assertEqual(contexts[1]['previous']['last_result']['status'],'REJECTED_IK')
   self.assertEqual(contexts[1]['previous']['last_action'],first)
   self.assertIsNotNone(contexts[1]['previous']['last_result']['original_target'])
   self.assertEqual(contexts[1]['task'],'unchanged task')
   self.assertEqual(read_json(run/'step-01/executed_action.json'),{'arm':None,'gripper':None})
   self.assertTrue((run/'step-01/after_state.json').exists())
   self.assertEqual(len(motions),1)
   if command_fault:
    self.assertEqual(code,1);self.assertEqual(len(contexts),2);self.assertIn('ARM_COMMAND_RETURN:1',summary['reason'])
   else:
    self.assertEqual(code,0);self.assertEqual(len(contexts),3);self.assertEqual(summary['status'],'MODEL_DONE')
   self.assertEqual(summary['hardware_commands_sent'],1)
 def test_three_reject_then_next_model_then_execute(self):self.run_loop('run_left_terminal.py')
 def test_four_reject_then_next_model_then_execute(self):self.run_loop('run_left_fourview.py')
 def test_ik_api_fault_stops(self):self.run_loop('run_left_terminal.py',ik_fault=True)
 def test_hardware_failure_stops_not_reclassified(self):self.run_loop('run_left_fourview.py',command_fault=True)
if __name__=='__main__':unittest.main()
