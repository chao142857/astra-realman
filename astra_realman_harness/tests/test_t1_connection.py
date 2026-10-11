"""Only the new normal-intent connection; no models or physics."""
from unittest.mock import patch
from platform_v1.research import t1_proposal as t
from test_action_proposal import ProposalTests
from test_geometry_first_v2 import PendingJob
class T1Connection(ProposalTests):
    def request(self):return t.request(self.w,self.o)
    def test_normal_proposal_uses_owner_admission_not_shadow(self):
        self.b.t1_episode_authorization=self.store.episode_id
        row=self.start();a=self.answer(row);a['result']['version']=t.VERSION
        self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        self.assertNotIn('derived_shadow',row);self.assertEqual(row['t1_candidate']['intent'],t.ROLE)
        self.assertIsNone(self.b.action_ready);self.assertFalse(row['grants_execution'])
        self.assertEqual(row['execution_class'],'OWNER_ADMISSION_REQUIRED')
    def answer(self,row,decision='planned'):
        row['proposal_host']=row['t1_proposal_host']
        a=super().answer(row,decision);del row['proposal_host'];return a
    def test_normal_requires_explicit_episode_authorization(self):
        with self.assertRaisesRegex(ValueError,'EXPLICIT_EPISODE_AUTH'):self.start()
    def test_shadow_raw_cannot_enter_new_normal_contract(self):
        self.b.t1_episode_authorization=self.store.episode_id
        row=self.start();a=self.answer(row);self.finish(row,a);self.assertEqual(row['status'],'FAILED')
