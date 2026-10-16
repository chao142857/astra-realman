"""Unit fixtures only: no physics evidence, hardware, Bridge or network."""
import ast,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from contact_preflight_v2 import ContactGuard,deferred_closing


class Guard(unittest.TestCase):
    def world(self,pairs=None):
        query=N(check_collision=lambda:pairs or [])
        arm=N(robot=N(get_qpos=lambda:[-.3]),master=0,joints=[N(get_drive_target=lambda:[-.4])],
            state=lambda:{'actual_pad_gap_m':.06},bilateral_pad_contact=lambda:False,
            motion=N(planning_world=query))
        return N(steps=7,arms={'left':arm},scene=N(get_contacts=lambda:[]))
    def test_only_explicit_closing_contact_mode_is_deferred(self):
        plans={'left':{'contact_mode':'bilateral_hold','closing':True},'right':{'contact_mode':'position','closing':True}}
        self.assertEqual(deferred_closing(plans),['left'])
        for p in ({'closing':True},{'contact_mode':'bilateral_hold','closing':False}):self.assertEqual(deferred_closing({'left':p}),[])
    def test_forbidden_pair_is_never_filtered_or_allowed_after_latch(self):
        for pair in [('left','Support_Link','table','table'),('left','Right_2_Link','cube','cube')]:
            with tempfile.TemporaryDirectory() as d:
                w=self.world([N(object_name1=pair[0],link_name1=pair[1],object_name2=pair[2],link_name2=pair[3])])
                w.arms['left'].bilateral_pad_contact=lambda:True
                guard=ContactGuard(w,Path(d),{'left':{'opening':.15}},['left'])
                with patch('contact_preflight_v2.refresh_actual_scene'),self.assertRaisesRegex(RuntimeError,'CONTACT_GUARD_COLLISION'):
                    guard.check('after_physics',105,{'left'})
                guard.close();s=json.loads((Path(d)/'contact_guard_summary_PRIVATE.json').read_text())
                self.assertEqual(s['first_bilateral_step']['left'],7);self.assertIsNotNone(s['first_danger'])
                self.assertEqual(w.steps,7)
    def test_no_contact_is_unknown_not_a_success_claim(self):
        with tempfile.TemporaryDirectory() as d:
            guard=ContactGuard(self.world(),Path(d),{},['left'])
            with patch('contact_preflight_v2.refresh_actual_scene') as refresh:guard.check('before_physics',0,set())
            guard.close();s=json.loads((Path(d)/'contact_guard_summary_PRIVATE.json').read_text())
            self.assertIsNone(s['first_bilateral_step']['left']);self.assertIsNone(s['first_danger'])
            self.assertTrue(s['empty_space_closure_is_not_safety_proof']);refresh.assert_called_once()
    def test_new_pad_contact_does_not_silently_promote_table_cube_to_carried(self):
        from contact_preflight_v2 import refresh_actual_scene
        w=self.world();w.collision_holder=None;updated=[]
        w.arms['left'].bilateral_pad_contact=lambda:True
        w.arms['left'].motion.update_from_simulation=lambda:updated.append('left')
        refresh_actual_scene(w,{})
        self.assertIsNone(w.collision_holder);self.assertEqual(updated,['left'])
    def test_source_does_not_write_physical_pose_qpos_or_drive_targets(self):
        t=ast.parse(Path(__file__).with_name('contact_preflight_v2.py').read_text())
        forbidden={'set_pose','set_root_pose','set_qpos','set_drive_target','set_drive_property'}
        self.assertFalse([n.attr for n in ast.walk(t) if isinstance(n,ast.Attribute) and n.attr in forbidden])
    def test_native_monitor_ik_acm_and_latch_are_bytecode_structure_unchanged(self):
        root=Path(__file__).parent
        old=subprocess.check_output(['git','show','624d80f:experiments/rm65_handoff_v1/dual_scene.py'],text=True)
        current=(root/'dual_scene.py').read_text()
        def methods(source):return {(c.name,f.name):ast.dump(f,include_attributes=False) for c in ast.parse(source).body if isinstance(c,ast.ClassDef) for f in c.body if isinstance(f,ast.FunctionDef)}
        a,b=methods(old),methods(current)
        for key in [('DualScene','tick'),('Arm','plan_tcp'),('Arm','init_planner'),('Arm','latch_grasp_contact'),('Arm','bilateral_pad_contact')]:self.assertEqual(a[key],b[key],key)
        for name in ('scene_v4_ready_transfer_1100.json','right_hold_velocity_v3.py','process_criteria_v1.json','carry_collision.py'):
            archived=subprocess.check_output(['git','show','624d80f:experiments/rm65_handoff_v1/'+name]);self.assertEqual(archived,(root/name).read_bytes(),name)


if __name__=='__main__':unittest.main(verbosity=2)
