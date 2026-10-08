"""Vocabulary/early rejection regressions; archived raw is never executed."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import jsonschema
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp import requirements as req,rgb,dependencies as dep
from sim_skills.full_pnp.protocol import wire_base,Memory,CandidateGate,Rejected
from sim_skills.full_pnp.wire import parse_actual_raw,parse_bridge_record,schema_for_role
from sim_skills.full_pnp.slot import FullSlot
import test_full_pnp_review as review

FIXTURE=Path(__file__).parent/'fixtures/qualification_b003_requirements'


class RequirementTests(unittest.TestCase):
    def setUp(self):
        self.w={'role':'B','binding':{'request_id':'synthetic'},'attachments':[{'id':'i'}],'evidence_packet_hash':None}
        self.c={'kind':'candidate','binding':self.w['binding'],'operation':'observe','actions':[],
                'requirements':['scene_healthy'],'evidence_refs':['i'],'parent_evidence_hash':None,'verdict':None,'reason':'synthetic'}
    def test_same_vocabulary_in_schema_projection_parser_and_RGB(self):
        obs,_=review.geometry();obs.update(captured_monotonic=1,capture_span_s=0)
        wire=wire_base(obs,{'history_cutoff':2},{'status':'completed'},[0,0,.15,0,1,0,0],Memory(),'B',0,'B')
        self.assertEqual(wire['model_requirements_contract']['allowed'],list(req.ALLOWED))
        self.assertEqual(wire['model_requirements_contract']['meanings'],req.PREDICATES)
        self.assertIn('not names the model',wire['owner_dependency_contract']['namespace'])
        for role in ('B','A'):
            self.w['role']=role
            self.assertEqual(schema_for_role(self.w)['properties']['requirements']['items']['enum'],list(req.ALLOWED))
            for name in req.ALLOWED:
                self.c['requirements']=['scene_healthy',name]
                self.assertEqual(parse_actual_raw(json.dumps(self.c),self.w),self.c)
                result=rgb.compare({}, {}, {}, {}, [name], {})
                self.assertEqual(result['status'],'unknown')  # Known predicate lacks evidence; never default pass.
                self.assertEqual(wire['rgb_applicability_contract'][name],req.PREDICATES[name])
        self.w['role']='E';self.assertNotIn('requirements',schema_for_role(self.w)['properties'])
    def test_missing_empty_wrong_type_and_unknown_declarations_are_rejected(self):
        for value in (None,[],['object_static'],['scene_healthy',13],['scene_healthy','bounded_upward_withdrawal'],['scene_healthy','current_triangulated_object']):
            with self.subTest(value=value):
                c=dict(self.c,requirements=value);before=copy.deepcopy(c)
                with self.assertRaises((ValueError,jsonschema.ValidationError)):parse_actual_raw(json.dumps(c),self.w)
                self.assertEqual(c,before)
        c=copy.deepcopy(self.c);del c['requirements']
        with self.assertRaises(jsonschema.ValidationError):parse_actual_raw(json.dumps(c),self.w)
    def test_done_requires_goal_while_observe_stop_remain_legal(self):
        for operation in ('observe','stop','finish'):
            c=dict(self.c,operation=operation,verdict='unknown')
            self.assertEqual(parse_actual_raw(json.dumps(c),self.w),c)
        c=dict(self.c,operation='finish',verdict='done')
        with self.assertRaisesRegex(ValueError,'FINISH_RGB_REQUIREMENTS'):parse_actual_raw(json.dumps(c),self.w)
        c['requirements'].append('object_at_goal')
        self.assertEqual(parse_actual_raw(json.dumps(c),self.w),c)
    def test_unknowns_rejected_before_geometry_RGB_or_owner_submission(self):
        for name in ('bounded_upward_withdrawal','current_triangulated_object','object_tracks_tool','fabricated'):
            with self.subTest(name=name),patch.object(dep,'hand_evidence') as geometry:
                with self.assertRaisesRegex(ValueError,'UNSUPPORTED_RGB_REQUIREMENT:'+name):
                    dep.check([],None,None,None,None,model_requirements=['scene_healthy',name])
                geometry.assert_not_called()
                with self.assertRaisesRegex(ValueError,'UNSUPPORTED_RGB_REQUIREMENT:'+name):rgb.compare({}, {}, {}, {}, [name], {})
            b={k:'fixture' for k in ('episode_id','task_revision','calibration_revision','action_interface_revision','parent_plan_id','expected_join_id','barrier_epoch')}
            c=dict(self.c,binding=b,requirements=['scene_healthy',name])
            item={'candidate':c,'snapshot':dict(self.w,binding=b),'digest':name,'deadline':100}
            with self.assertRaisesRegex(Rejected,'UNSUPPORTED_RGB_REQUIREMENT:'+name):
                CandidateGate().validate(item,b, {},1,{'status':'valid'},{'i'})
    def test_owner_minimums_survive_minimal_model_declaration(self):
        old=review.geometry();changed=review.geometry(obj=(.1,0,.025))
        out=dep.check([{'type':'move_pose','pose':[.1,0,.10,0,1,0,0]}],old[0],changed[0],old[1],changed[1],model_requirements=['scene_healthy'])
        self.assertIn('object_static',out['owner_required']);self.assertEqual(out['status'],'invalid')
        old=review.geometry(tool=(0,0,.10),obj=(0,0,.10));new=review.geometry(tool=(.1,0,.10),obj=(.1,0,.10),goal=(.35,.1,0))
        out=dep.check([{'type':'move_pose','pose':[.2,.1,.10,0,1,0,0]}],old[0],new[0],old[1],new[1],model_requirements=['scene_healthy'])
        self.assertTrue({'goal_static','object_near_tool'}<=set(out['owner_required']))
        self.assertEqual(out['status'],'invalid')
        self.assertIn('object_tracks_tool',[c['requirement'] for c in out['checks']])
    def test_archived_B003_old_schema_accepts_new_schema_parser_reject_unchanged(self):
        manifest=json.loads((FIXTURE/'manifest.json').read_text())
        for name,record in manifest['files'].items():self.assertEqual(hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest(),record['sha256'])
        raw=(FIXTURE/'raw.json').read_text();wire=json.loads((FIXTURE/'wire.json').read_text());answer=json.loads(raw)
        jsonschema.validate(answer,json.loads((FIXTURE/'original_schema.json').read_text()))
        with self.assertRaises(jsonschema.ValidationError) as err:parse_actual_raw(raw,wire)
        self.assertEqual(list(err.exception.path)[0],'requirements')
        self.assertIn(err.exception.instance,('bounded_upward_withdrawal','current_triangulated_object'))
        self.assertEqual((FIXTURE/'raw.json').read_text(),raw)
        self.assertEqual(manifest['historical_result'],{'B':'FAIL','F':'NOT_RUN','real_model_calls':3})
    def test_archived_B003_consumes_attempt_but_never_becomes_ready_or_retries(self):
        raw=(FIXTURE/'raw.json').read_text();wire=json.loads((FIXTURE/'wire.json').read_text())
        class Finished:
            returncode=0
            def poll(self):return 0
        with tempfile.TemporaryDirectory() as temp:
            s=FullSlot(Path(temp)/'slot',lambda *_:None,infer_config=SimpleNamespace(source='OFFLINE_RAW_REPLAY_NO_INFER'));s.calls=1
            run=s.root/'request-001';run.mkdir(parents=True)
            stdout=(run/'worker.json').open('x');stdout.write(json.dumps({'raw':raw,'error':None,'return_code':0,'usage':None}));stdout.flush()
            s.attempts[1]={'request':1,'role':'B','usage_raw':None,'stages':[]}
            s.job={'process':Finished(),'run':run,'stdout':stdout,'stderr':(run/'stderr.log').open('x'),
                   'snapshot':wire,'digest':'synthetic-rejection-only','started':0,'deadline':1e20,'candidate_deadline':1e20}
            with patch.object(s,'_prepare_launch') as launch:
                with self.assertRaisesRegex(Rejected,'NO_RETRY'):s.poll()
                launch.assert_not_called()
            self.assertEqual(s.attempts[1]['status'],'PARSE_FAILED');self.assertIsNone(s.pending)
            self.assertEqual(s.calls,1);self.assertFalse((run/'parsed.json').exists())
            self.assertEqual(json.loads((run/'worker.json').read_text())['raw'],raw)


if __name__=='__main__':unittest.main()
