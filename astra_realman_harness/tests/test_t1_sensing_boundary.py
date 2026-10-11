"""SYNTHETIC no-action boundary contracts; not physical evidence."""
import unittest
from test_geometry_first_update import UpdateTests

class SensingBoundaryTests(UpdateTests):
    def test_no_action_boundary_updates_measured_state_without_claiming_execution(self):
        o,fb=self.injected();o['execution_epoch']=self.o['execution_epoch'];self.epoch=o['execution_epoch']
        self.store.observations.pop(o['observation_id']);self.store.observe(o,self.epoch)
        fb.update(kind='OBSERVATION_ONLY_NO_ACTION',actions=[],owner_submissions=0,execution_epoch=self.epoch)
        w=self.update(o,fb)
        self.assertEqual(w['state']['entities']['object_004']['observation_id'],o['observation_id'])
        self.assertEqual(w['state']['execution_feedback']['actions'],[])
        self.assertEqual(w['binding']['execution_epoch'],self.w['binding']['execution_epoch'])
    def test_no_action_boundary_cannot_conceal_changed_epoch(self):
        o,fb=self.injected();fb.update(kind='OBSERVATION_ONLY_NO_ACTION',actions=[],owner_submissions=0)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_ONLY_EPOCH_CHANGED'):self.update(o,fb)
    def test_no_action_boundary_cannot_claim_action(self):
        o,fb=self.injected();fb.update(kind='OBSERVATION_ONLY_NO_ACTION',actions=[{'completed':True}],owner_submissions=1)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_ONLY_CANNOT_CLAIM_ACTION'):self.update(o,fb)
