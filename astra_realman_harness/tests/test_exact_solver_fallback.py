import copy,ctypes,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from exact_target_feasibility import solve_exact_inputs

class Robot:
    def __init__(self):
        self.codes=[1,1];self.inputs=[];self.modes=[];self.rows=[];self.limits={};self.model='RM_65';self.result=1
    def rm_algo_inverse_kinematics(self,p):
        self.inputs.append(copy.deepcopy(p));code=self.codes[len(self.inputs)-1]
        p['q_pose'][0]=999 # cannot contaminate subsequent params
        return code,[0.]*6
    def rm_algo_set_redundant_parameter_traversal_mode(self,mode):self.modes.append(mode)
    def rm_get_robot_info(self):return 0,{'arm_dof':6,'arm_model':self.model}
    def rm_algo_inverse_kinematics_all(self,p):
        self.inputs.append(copy.deepcopy(p))
        return NS(result=self.result,num=len(self.rows),q_ref=[0]*8,q_solve=self.rows)
    def rm_algo_ikine_check_joint_position_limit(self,q):
        assert isinstance(q,ctypes.Array)
        return self.limits.get(q[0],0)

class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.r=Robot();self.seed=[1.,2.,3.,4.,5.,6.];self.target=[.1,.2,.3,0.,0.,0.]
    def solve(self,arm='left',**kw):
        session=NS(connected={arm:self.r},sdk=NS(rm_inverse_kinematics_params_t=lambda **k:k))
        return solve_exact_inputs(session,arm,self.seed,self.target,**kw)
    def test_fast(self):
        self.r.codes=[0];o=self.solve();self.assertEqual(o['status'],'PASS_IK');self.assertEqual(o['solver_path'],['fast']);self.assertEqual(self.r.modes,[])
    def test_traversal_identical(self):
        self.r.codes=[1,0];o=self.solve();self.assertEqual(o['selected_solver'],'traversal');self.assertEqual(self.r.inputs[0],self.r.inputs[1]);self.assertEqual(self.r.modes,[True,False])
    def test_all_nearest_valid_both_arms(self):
        for arm in ('left','right'):
            self.r=Robot();self.r.result=0;self.r.rows=[[1]*8,[2]*8,[3]*8];self.r.limits={3.:4}
            o=self.solve(arm);self.assertEqual(o['selected_solution'],[2]*6);self.assertEqual(o['selected_candidate_index'],1)
            self.assertTrue(all(p==self.r.inputs[0] for p in self.r.inputs));self.assertEqual(o['exact_target_pose'],self.target)
    def test_all_failed(self):
        o=self.solve();self.assertEqual(o['status'],'REJECTED_IK');self.assertEqual(o['solver_path'],['fast','traversal','all_solutions'])
    def test_all_outside_limits(self):
        self.r.result=0;self.r.rows=[[2]*8];self.r.limits={2.:1};self.assertEqual(self.solve()['status'],'REJECTED_IK')
    def test_fast_api_error(self):
        self.r.codes=[-2];o=self.solve();self.assertEqual(o['status'],'CHECK_ERROR');self.assertEqual(self.r.modes,[])
    def test_traversal_error_restores(self):
        self.r.codes=[1,-2];self.assertEqual(self.solve()['status'],'CHECK_ERROR');self.assertEqual(self.r.modes,[True,False])
    def test_model_unknown(self):
        self.r.model='RM_75';self.assertEqual(self.solve()['status'],'CHECK_ERROR');self.assertEqual(len(self.r.inputs),2)
    def test_all_api_error(self):
        self.r.result=-1;self.assertEqual(self.solve()['status'],'CHECK_ERROR')
    def test_invalid_candidate(self):
        self.r.result=0;self.r.rows=[[float('nan')]*8];self.assertEqual(self.solve()['status'],'CHECK_ERROR')
    def test_joint_checker_error(self):
        self.r.result=0;self.r.rows=[[2]*8];self.r.limits={2.:-1};self.assertEqual(self.solve()['status'],'CHECK_ERROR')
    def test_diagnostic_runs_all(self):
        self.r.codes=[0,0];o=self.solve(all_stages=True);self.assertEqual(len(self.r.inputs),3);self.assertEqual(o['selected_solver'],'fast')
    def test_overflow_no_call(self):
        self.target[0]=1e100;self.assertEqual(self.solve()['status'],'CHECK_ERROR');self.assertEqual(self.r.inputs,[])
    def test_reset_failure(self):
        def mode(x):
            if not x:raise RuntimeError('reset failed')
        self.r.rm_algo_set_redundant_parameter_traversal_mode=mode
        self.r.codes=[1,0];self.assertEqual(self.solve()['status'],'CHECK_ERROR')
if __name__=='__main__':unittest.main()
