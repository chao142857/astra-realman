import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.groups import decide_group, CONDITIONS, VERSION
from bimanual_demo.state import TaskState
from bimanual_demo.protocol import action


class GroupsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        revision={'camera':'c','layout':'l','calibration':'k'}
        self.proposal=action(TaskState({},revision),'OBSERVE')
        self.common={'binding':{'observation_id':'o1','state_version':0,'revision':revision},
                     'evidence_refs':['image-hash'],'images':['same-image'],'state':{'right':'unknown'}}
        self.seen=[]
    def tearDown(self):self.tmp.cleanup()
    def stub(self,request,folder,**kw):
        self.seen.append(copy.deepcopy(request));parent=request['parent_message'];observer=request['role']=='observer'
        return {'version':VERSION,'binding':request['common']['binding'],'claims':[],
                'proposal':None if observer else copy.deepcopy(self.proposal),
                'disposition':'EVIDENCE_ONLY' if observer else ('REVISE' if parent else 'PROPOSE'),
                'parent_sha256':request['parent_sha256'],'reason':'fixture'}
    def run_group(self,condition,call=None,**kw):
        return decide_group(self.common,condition,call or self.stub,self.root/condition,
                            stop=kw.pop('stop',threading.Event()),**kw)
    def test_call_counts_and_same_common_input(self):
        for condition,count in zip(CONDITIONS,[1,2,2,2]):
            result=self.run_group(condition)
            self.assertEqual(result['model_attempts'],count)
            self.assertEqual(result['status'],'VALID_PROPOSAL')
        self.assertTrue(all(x['common']==self.common for x in self.seen))
    def test_second_call_failure_never_falls_back_to_draft(self):
        def bad(r,f,**k):
            if r['parent_message']:raise RuntimeError('backend failure')
            return self.stub(r,f,**k)
        result=self.run_group('S1+',bad)
        self.assertEqual(result['model_attempts'],2);self.assertIsNone(result['final_proposal'])
    def test_keep_with_changes_rejected_for_both_major_conditions(self):
        def bad(r,f,**k):
            v=self.stub(r,f,**k)
            if r['parent_message']:v['disposition']='KEEP';v['proposal']['intent']='changed'
            return v
        for condition in ('S1+','A2-arm'):
            result=self.run_group(condition,bad)
            self.assertIn('KEEP_CHANGED',result['error']);self.assertIsNone(result['final_proposal'])
    def test_parent_hash_and_claim_source_are_checked(self):
        def bad(r,f,**k):
            v=self.stub(r,f,**k)
            if r['parent_message']:v['parent_sha256']='wrong'
            return v
        self.assertIn('PARENT_HASH',self.run_group('A2-arm',bad)['error'])
        def forged(r,f,**k):
            v=self.stub(r,f,**k);v['claims']=[{'predicate':'held','value':'true','evidence_refs':['image-hash'],'source':'validated_observer'}];return v
        self.assertIn('CLAIM_SOURCE',self.run_group('S1',forged)['error'])
    def test_no_proposal_does_not_become_action(self):
        def no(r,f,**k):
            v=self.stub(r,f,**k);v.update(disposition='NO_PROPOSAL',proposal=None);return v
        self.assertEqual(self.run_group('S1',no)['status'],'VALID_NO_PROPOSAL')
    def test_stop_and_late_output_are_not_submitted(self):
        stop=threading.Event()
        def late(r,f,**k):v=self.stub(r,f,**k);stop.set();return v
        result=self.run_group('S1+',late,stop=stop)
        self.assertEqual(result['model_attempts'],1);self.assertIsNone(result['final_proposal'])


if __name__=='__main__':unittest.main()
