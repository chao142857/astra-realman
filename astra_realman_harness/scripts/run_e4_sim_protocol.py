#!/usr/bin/env python3
"""Four recorded simulation checkpoints, 28 STUB calls; not official G evaluation."""
import argparse
import json
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bimanual_demo.protocol import action
from bimanual_demo.state import TaskState
from sim_skills.model import input_payload
from sim_skills.groups import CONDITIONS, VERSION, decide_group


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    contexts=[]
    with a.events.open() as stream:
        for line in stream:
            row=json.loads(line)
            if row['kind']=='MODEL_ATTEMPT':contexts.append(input_payload(row['data']['context'])['context'])
            if len(contexts)==4:break
    if len(contexts)!=4:raise ValueError('FOUR_RECORDED_M_REQUESTS_REQUIRED')
    revision={'camera':'sim-rgb-v1','layout':'rm65-fixed-v1','calibration':'SIM_ONLY'}
    state=TaskState({},revision)
    proposal=action(state,'OBSERVE')
    def stub(request,folder,*,timeout_s):
        parent=request['parent_message'];observer=request['role']=='observer'
        return {'version':VERSION,'binding':request['common']['binding'],
                'claims':[{'predicate':'holding visually decidable','value':'unknown',
                           'evidence_refs':[],'source':'model_judgment'}],
                'proposal':None if observer else proposal,
                'disposition':'EVIDENCE_ONLY' if observer else ('REVISE' if parent else 'PROPOSE'),
                'parent_sha256':request['parent_sha256'],'reason':'STUB protocol qualification only'}
    results=[]
    for index,context in enumerate(contexts):
        common={'binding':{'observation_id':context['binding']['observation_id'],'state_version':0,'revision':revision},
                'input':context,'skill_catalog':['OBSERVE'], 'right_arm_state':'UNKNOWN_UNAVAILABLE',
                'evidence_refs':[r['sha256'] for r in context['images_in_attachment_order']],
                'source':'RECORDED_PHYSICS_IMAGES_WITH_PROTOCOL_FIXTURE_TASK_STATE'}
        for condition in CONDITIONS:
            result=decide_group(common,condition,stub,a.output/('%d-%s'%(index+1,condition)),stop=threading.Event())
            results.append(result)
    summary={'status':'PASS' if all(x['status']=='VALID_PROPOSAL' for x in results) else 'FAIL',
             'stub_calls':sum(x['model_attempts'] for x in results),'real_model_calls':0,'hardware_calls':0,
             'physical_source_episodes':1,'protocol_only':True,'official_G_qualified':False,
             'note':'No skill execution, human labels or E4 research result. All 4 checkpoints share one source episode.',
             'results':results}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='results'}))
    return 0 if summary['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
