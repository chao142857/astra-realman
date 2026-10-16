"""No NumPy/SAPIEN/network: public contract and operation scheduling only."""
import copy,importlib.util,json,unittest
from pathlib import Path
import jsonschema
from chunk_protocol_v2_1 import SCHEMA,STAGE_RULES,stage_batches,validate_control_semantics


def tcp(side,x):return {'arm':side,'kind':'tcp','waypoints_world_wxyz':[[x,0,.2,0,1,0,0]]}
def grip(side):return {'arm':side,'kind':'gripper','opening_fraction':.37,'contact_mode':'position'}
def chunk(actions,mode='sequential'):return {'done':False,'stages':[{'mode':mode,'observe_s':0.,'actions':actions}]}


class Protocol(unittest.TestCase):
    def valid(self,value):jsonschema.validate(value,SCHEMA);validate_control_semantics(value)
    def test_archived_d4_is_valid_without_edits(self):
        p=Path(__file__).parent/'evidence/full_task_real_20261016/episode/decision_003/raw.txt'
        value=json.loads(p.read_text());original=copy.deepcopy(value);self.valid(value)
        self.assertEqual(value,original);self.assertEqual(value['stages'][2]['actions'][0]['arm'],'left')
    def test_sequential_duplicates_and_mixed_operations_are_public(self):
        for actions in ([tcp('left',.21),tcp('left',.22)],[tcp('left',.21),grip('left')],[grip('left'),grip('left')]):
            self.valid(chunk(actions))
        self.assertIn('same arm may occur more than once',SCHEMA['properties']['stages']['items']['description'])
    def test_parallel_conflict_is_explicit_and_fails_before_scheduling(self):
        for actions in ([tcp('left',.21),tcp('left',.22)],[tcp('left',.21),grip('left')]):
            v=chunk(actions,'parallel');jsonschema.validate(v,SCHEMA)
            # Cross-item key uniqueness is explicitly public semantic validation;
            # the original Bridge schema subset cannot encode this rule.
            with self.assertRaisesRegex(ValueError,'PARALLEL'):validate_control_semantics(v)
            with self.assertRaises(ValueError):next(stage_batches(None,v['stages'][0],lambda a:None,lambda a,p:[]))
        self.assertIn('repeated arms are a conflict',STAGE_RULES)
    def test_sequential_lazily_reads_state_and_never_overwrites(self):
        class World:arms={'left':{'pose':[.2,0,.2,0,1,0,0]}}
        w=World();calls=[]
        def nodes(action,start):
            calls.append((copy.deepcopy(action),copy.deepcopy(start)))
            return [{'pose':action['waypoints_world_wxyz'][0]}] if action['kind']=='tcp' else [{'opening':action['opening_fraction']}]
        value=chunk([tcp('left',.21),grip('left')]);original=copy.deepcopy(value)
        g=stage_batches(w,value['stages'][0],lambda a:a['pose'].copy(),nodes)
        first=next(g);self.assertEqual(len(calls),1);self.assertEqual(first[1],{'left':0})
        w.arms['left']['pose']=[.211,0,.2,0,1,0,0]
        second=next(g);self.assertEqual(calls[1][1][0],.211);self.assertEqual(second[1],{'left':1})
        self.assertEqual(second[0]['left']['opening'],.37);self.assertEqual(value,original)
        with self.assertRaises(StopIteration):next(g)
    def test_identical_sequential_targets_are_two_distinct_operations(self):
        class World:arms={'left':0}
        a=tcp('left',.21);v=chunk([a,copy.deepcopy(a)])
        out=list(stage_batches(World(),v['stages'][0],lambda _:0,lambda action,p:[{'pose':action['waypoints_world_wxyz'][0]}]))
        self.assertEqual([x[1]['left'] for x in out],[0,1]);self.assertEqual(len(out),2)
    def test_parallel_unique_arms_keep_overlap(self):
        class World:arms={'left':0,'right':0}
        v=chunk([tcp('left',.21),tcp('right',.51)],'parallel');self.valid(v)
        out=list(stage_batches(World(),v['stages'][0],lambda _:0,lambda a,p:[{'pose':a['waypoints_world_wxyz'][0]}]))
        self.assertEqual(len(out),1);self.assertEqual(set(out[0][0]),{'left','right'})
    def test_bridge_schema_compiler_unchanged_accepts_contract(self):
        file=Path(__file__).resolve().parents[2]/'astra_realman_harness/scripts/structured_outputs.py'
        spec=importlib.util.spec_from_file_location('_unchanged_schema_compiler',file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        provider,audit=module.compile_schema(SCHEMA);self.assertEqual(audit['status'],'PASS')
        value=chunk([tcp('left',.21),grip('left')]);module.validate_local(value,SCHEMA,provider)
    def test_empty_and_done_semantics(self):
        self.valid({'done':True,'stages':[]})
        for v in ({'done':False,'stages':[]},chunk([])):
            with self.assertRaises(ValueError):validate_control_semantics(v)


if __name__=='__main__':unittest.main(verbosity=2)
