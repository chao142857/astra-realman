#!/usr/bin/env python3
"""Export actual final provider/local schemas from an offline CLI suite, no calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from platform_v1.research import chunk_plan, contracts
from platform_v1.research.broker import output_contract
from sim_skills.full_pnp.wire import schema_for_role
from scripts.structured_outputs import compile_schema, encoded, sha

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',type=Path,required=True)
    p.add_argument('--legacy-wire',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);manifest={}
    def export(name,local,origin):
        provider,audit=compile_schema(local)
        for suffix,value in (('provider.schema',provider),('authoritative.schema',local),('audit',audit)):
            (a.output/(name+'.'+suffix+'.json')).write_bytes(encoded(value))
        manifest[name]={'provider_sha256':sha(provider),'authoritative_sha256':sha(local),
            'node_count':len(audit['nodes']),'origin':origin,'status':'OFFLINE_SUBSET_PASS'}
    def load(case):return json.loads((a.suite/case/'broker/broker-001/input_only/payload.json').read_text())
    for name in ('e0','action_h4','local_reground'):
        payload=load(name);export(name,payload['authoritative_schema'],str(a.suite/name))
        assert sha(payload['schema'])==manifest[name]['provider_sha256']
    action=load('action_h4');w=action['context'];properties=action['authoritative_schema']['properties']['result']['properties']
    world=json.loads((a.suite/'action_h4/SYNTHETIC_WORLD.json').read_text())
    obs=json.loads((a.suite/'action_h4/SYNTHETIC_OBSERVATION.json').read_text())
    (a.output/'SYNTHETIC_WORLD.json').write_bytes(encoded(world))
    (a.output/'SYNTHETIC_OBSERVATION.json').write_bytes(encoded(obs))
    for H in (1,6,8):
        result=chunk_plan.request_schema(world,obs,properties['task']['const'],properties['task_binding']['const'],H,w['binding']['evidence_ids'])
        local,_,_=output_contract(result,w['binding'],[x['id'] for x in w['attachments']],w['binding']['evidence_ids'])
        export('action_h'+str(H),local,'SAME_FROZEN_SYNTHETIC_WORLD; production request_schema + Broker envelope')
    for name,shape in (('research_action_v1',contracts.plan_schema()),('local_reground_regions',contracts.semantic_schema())):
        local,_,_=output_contract(shape,w['binding'],[x['id'] for x in w['attachments']],w['binding']['evidence_ids'])
        export(name,local,'production compatibility schema + Broker envelope')
    legacy=json.loads(a.legacy_wire.read_text())
    for role in ('B','E','A'):
        wire=copy.deepcopy(legacy);wire['role']=role
        export('legacy_'+role,schema_for_role(wire),{'wire':str(a.legacy_wire),
            'sha256':hashlib.sha256(a.legacy_wire.read_bytes()).hexdigest(),'role':role})
    (a.output/'MANIFEST.json').write_bytes(encoded(manifest))
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
