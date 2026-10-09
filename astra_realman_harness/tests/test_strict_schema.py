import copy
import json
import tempfile
import unittest
import jsonschema
from unittest.mock import patch
from pathlib import Path
from platform_v1.research import fusion, integration, chunk_plan, contracts
from scripts.structured_outputs import compile_schema, check_provider, constant, encoded
from sim_skills.full_pnp.infer_process import InferConfig
from scripts.prepare_research_fake_cli import prepare as fake_cli
from research_fixtures import owner
from strict_schema_fixtures import prepare, complete, semantic_answer, synthetic_world, action_request, action_answer

class SchemaTests(unittest.TestCase):
    def test_recursive_missing_types_rejected(self):
        provider,_=compile_schema(fusion.semantic_schema())
        def nodes(s):
            yield s
            for c in s.get('properties',{}).values(): yield from nodes(c)
            if 'items' in s: yield from nodes(s['items'])
        for node in list(nodes(provider)):
            t=node.pop('type')
            with self.assertRaises(ValueError): check_provider(provider)
            node['type']=t
    def test_unbound_dynamic_map_fails(self):
        with self.assertRaisesRegex(ValueError,'DYNAMIC|CLOSED'): compile_schema(chunk_plan.plan_schema())
    def test_types_null_arrays_and_objects(self):
        for value in (None,True,1,1.2,'x',[],['a','b'],{'id':None,'values':[1,2]}):
            schema={'type':'object','properties':{'value':constant(value)},'required':['value'],'additionalProperties':False}
            p,a=compile_schema(schema); self.assertEqual(a['status'],'PASS')
            self.assertEqual(compile_schema(json.loads(encoded(schema)))[0],p)
    def test_unsupported_keywords_closed_root_and_limits(self):
        good={'type':'object','properties':{},'required':[],'additionalProperties':False}
        bad=[{'type':'string'},{'anyOf':[good]},dict(good,additionalProperties={'type':'string'}),
             dict(good,oneOf=[good]),dict(good,required=['missing'])]
        for key in ('$ref','$defs','allOf','not','if','dependentRequired','patternProperties','default','oneOf'):
            bad.append(dict(good,**{key:{}}))
        bad.append(dict(good,description='x'*65537))
        deep={'type':'string'}
        for _ in range(11): deep={'type':'object','properties':{'x':deep},'required':['x'],'additionalProperties':False}
        bad.append(deep)
        bad.append(dict(good,properties={'x':{'type':'string','enum':[str(i) for i in range(1001)]}},required=['x']))
        for s in bad:
            with self.subTest(schema=str(s)[:80]), self.assertRaises((ValueError,TypeError,jsonschema.SchemaError)): check_provider(s)
    def test_legacy_oneof_local_preserved(self):
        local=contracts.plan_schema();p,a=compile_schema(local)
        self.assertIn('oneOf',local['properties']['waypoints']['items'])
        self.assertIn('anyOf',p['properties']['waypoints']['items'])
        self.assertTrue(a['changes'])

class BrokerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.o=owner(root/'owner',InferConfig(str(fake_cli(root/'cli')),fixture=True),cap=100)
        self.b=self.o.research.broker;self.obs=self.o.observe()
    def tearDown(self):self.o.close();self.tmp.cleanup()
    def row(self,action=False,H=4):
        e,j=prepare(self.b,integration.semantic_request(self.obs['observation_id']))
        if not action:return e,j,semantic_answer(e)
        complete(self.b,j,semantic_answer(e));self.assertEqual(e['status'],'READY',e.get('error'))
        world=synthetic_world(self.b.store,self.obs,e['evidence_id'])
        a,j=prepare(self.b,action_request(world,self.obs,H));return a,j,action_answer(a)
    def test_all_horizons_and_terminal(self):
        for H in (1,4,6,8):
            for terminal in (False,True):
                row,job,answer=self.row(True,H)
                if terminal:
                    answer['result']['waypoints']=answer['result']['waypoints'][:1]
                    answer['result']['waypoints'][-1]['boundary_after']='precontact_handoff'
                    answer['result']['termination']['kind']='stage_terminal'
                complete(self.b,job,answer);self.assertEqual(row['status'],'READY',row.get('error'))
                self.assertEqual(row['provenance'],'FAKE_MODEL_RAW');self.assertIsNone(row['usage_raw'])
                self.b.action_ready=None
        self.assertEqual(self.o.b.commands,[])
    def test_semantic_success_no_auto_action(self):
        row,job,a=self.row();complete(self.b,job,a);self.assertEqual(row['status'],'READY',row.get('error'))
        self.assertEqual(self.b.calls,1);self.assertEqual(self.o.b.commands,[])
    def reject(self,mutate,action=False):
        row,job,a=self.row(action);mutate(a);complete(self.b,job,a)
        self.assertEqual(row['status'],'FAILED',row);self.assertNotIn('evidence_id',row)
        self.assertIsNone(row['parsed']);self.assertIsNotNone(row['raw'])
    def test_negative_bindings_and_envelope(self):
        mutations=[lambda a:a.pop('binding'),lambda a:a['binding'].update(execution_epoch='0'),
          lambda a:a['binding'].update(world_id='not-null'),lambda a:a['binding'].update(world_revision='1'),
          lambda a:a.pop('evidence_refs'),lambda a:a.update(evidence_refs=[]),
          lambda a:a.update(evidence_refs=['UNSENT_IMAGE']),lambda a:a.update(extra=True),
          lambda a:a.update(producer='MODEL_RAW'),lambda a:a['binding'].update(raw_sha256='forged')]
        for m in mutations:self.reject(m)
    def test_negative_semantic_ids_and_pixels(self):
        mutations=[lambda a:a['result'].update(task_target_id='missing'),
          lambda a:a['result']['entities'].append(copy.deepcopy(a['result']['entities'][0])),
          lambda a:a['result']['entities'][0]['views'][0].update(attachment_id='UNSENT'),
          lambda a:a['result']['entities'][0]['views'][0].update(bbox=[.8,.2,.1,.4]),
          lambda a:a['result']['entities'][0].update(label=''),
          lambda a:a['result']['relations'].append({'subject':'missing','object':'missing',
              'predicate':'near','status':'hypothesis','evidence_refs':[a['evidence_refs'][0]]})]
        for m in mutations:self.reject(m)
    def test_negative_action_bindings_and_suffix(self):
        mutations=[lambda a:a['binding'].update(world_id=None),
          lambda a:a['result'].update(H=1),lambda a:a['result']['waypoints'].pop(),
          lambda a:a['result']['read_versions'].update({'task/SYNTHETIC':2}),
          lambda a:a['result']['read_versions'].update({'unread':1}),
          lambda a:a['result']['task_binding'].update(object_id='missing'),
          lambda a:a['result']['termination'].update(kind='stage_terminal'),
          lambda a:a['result']['waypoints'][1].update(prediction_dependencies=[]),
          lambda a:a['result'].update(producer='MODEL_RAW'),
          lambda a:a['result'].update(source={'producer':'MODEL_RAW','raw_sha256':'forged'}),
          lambda a:a['result'].update(execution_epoch=1),
          lambda a:a['result'].update(world_revision=999)]
        for m in mutations:self.reject(m,True)
    def test_stale_epoch_and_world_after_receipt(self):
        row,job,a=self.row();self.o.epoch+=1;complete(self.b,job,a)
        self.assertEqual(row['status'],'FAILED');self.assertIn('STALE_EXECUTION_EPOCH',row['error'])
        self.obs=self.o.observe();row,job,a=self.row(True);self.b.store.revision+=1;complete(self.b,job,a)
        self.assertEqual(row['status'],'FAILED');self.assertIn('STALE_WORLD_REVISION',row['error'])
    def test_strict_raw_duplicate_nan_truncated(self):
        for raw in ('{"binding":{},"binding":{}}','{"value":NaN}','{broken'):
            row,job,a=self.row();complete(self.b,job,raw=raw)
            self.assertEqual(row['status'],'FAILED');self.assertEqual(row['raw'],raw)
    def test_local_reground(self):
        request=integration.semantic_request(self.obs['observation_id']);request['role']='local_reground'
        row,job=prepare(self.b,request);complete(self.b,job,semantic_answer(row))
        self.assertEqual(row['status'],'READY',row.get('error'))
    def test_incompatible_nested_schema_fails_before_process(self):
        for key,value in (('additionalProperties',{'type':'string'}),('not',{'type':'string'})):
            request=integration.semantic_request(self.obs['observation_id'])
            request['output_schema']['properties']['entities']['items'][key]=value
            with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_DISPATCH')) as process:
                with self.assertRaises(ValueError):self.b.submit(request)
                process.assert_not_called()
            row=list(self.b.rows.values())[-1]
            self.assertEqual(row['status'],'FAILED');self.assertIsNone(row['raw']);self.assertIsNone(row['usage_raw'])

if __name__=='__main__': unittest.main()
