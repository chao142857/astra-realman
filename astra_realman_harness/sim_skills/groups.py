"""E4 same-cycle revision protocol; decision messages have no executor handle."""
import copy
import hashlib
import json
import time
from pathlib import Path
from bimanual_demo.protocol import parse

CONDITIONS = {'S1': ('central',), 'S1+': ('central', 'central'),
              'A2-arm': ('left_responsibility', 'right_responsibility'),
              'A2-role': ('observer', 'decision')}
VERSION = 'e4_same_cycle_revision_v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate(value, binding, *, parent=None, observer_only=False, evidence_refs=()):
    if set(value) != {'version','binding','claims','proposal','disposition','parent_sha256','reason'}:
        raise ValueError('E4_ENVELOPE')
    if value['version'] != VERSION or digest(value['binding']) != digest(binding):
        raise ValueError('E4_BINDING')
    if not isinstance(value['claims'],list) or len(value['claims']) > 6:
        raise ValueError('E4_CLAIM_BUDGET')
    if not isinstance(value['reason'],str) or len(value['reason']) > 240:
        raise ValueError('E4_REASON_BUDGET')
    for c in value['claims']:
        if set(c) != {'predicate','value','evidence_refs','source'} or c['source'] != 'model_judgment':
            raise ValueError('E4_CLAIM_SOURCE')
        if c['value'] not in ('true','false','unknown') or not isinstance(c['predicate'],str) or not 1 <= len(c['predicate']) <= 240:
            raise ValueError('E4_CLAIM_VALUE')
        if not isinstance(c['evidence_refs'],list) or any(r not in evidence_refs for r in c['evidence_refs']):
            raise ValueError('E4_EVIDENCE_REFERENCE')
    if parent is None:
        if value['parent_sha256'] is not None or value['disposition'] not in ('PROPOSE','NO_PROPOSAL','EVIDENCE_ONLY'):
            raise ValueError('E4_FIRST_CALL')
    else:
        if value['parent_sha256'] != digest(parent):raise ValueError('E4_PARENT_HASH')
        if value['disposition'] not in ('KEEP','REVISE','NO_PROPOSAL'):
            raise ValueError('E4_REVISION_DISPOSITION')
        if value['disposition'] == 'KEEP' and value['proposal'] != parent['proposal']:
            raise ValueError('E4_KEEP_CHANGED_PROPOSAL')
    if observer_only:
        if value['proposal'] is not None or value['disposition'] != 'EVIDENCE_ONLY':
            raise ValueError('OBSERVER_CANNOT_PROPOSE')
    elif value['disposition'] == 'EVIDENCE_ONLY':raise ValueError('FINAL_EVIDENCE_ONLY')
    if value['disposition'] in ('NO_PROPOSAL','EVIDENCE_ONLY'):
        if value['proposal'] is not None:raise ValueError('E4_NO_PROPOSAL_HAS_ACTION')
    else:
        proposal = parse(value['proposal'])  # Original high-level parser is unchanged.
        if proposal['state_version'] != binding['state_version'] or proposal['revision'] != binding['revision']:
            raise ValueError('E4_INNER_PROPOSAL_BINDING')
    return copy.deepcopy(value)


def decide_group(common, condition, call, output, *, stop, budget_s=240, clock=time.monotonic):
    if condition not in CONDITIONS:raise ValueError('E4_CONDITION')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    start=clock();deadline=start+budget_s;parent=None;records=[]
    summary={'version':VERSION,'condition':condition,'status':'INCOMPLETE','final_proposal':None,
             'executor_present':False,'hardware_calls':0,'model_attempts':0}
    try:
        for index, role in enumerate(CONDITIONS[condition]):
            if stop.is_set():raise RuntimeError('STOP_NO_NEW_REQUEST')
            if clock()>=deadline:raise TimeoutError('E4_BUDGET')
            request={'common':copy.deepcopy(common),'role':role,'version':VERSION,
                     'parent_message':copy.deepcopy(parent),'parent_sha256':digest(parent) if parent else None,
                     'message_rule':'Model claims are untrusted; only this cycle. All roles see identical common input.'}
            folder=output/('call-%d'%(index+1));folder.mkdir()
            (folder/'input.json').write_text(json.dumps(request,indent=2))
            summary['model_attempts']+=1
            raw=call(request,folder,timeout_s=min(120,deadline-clock()))
            (folder/'raw.json').write_text(json.dumps(raw,indent=2))
            if stop.is_set() or clock()>=deadline:raise TimeoutError('STOP_OR_LATE_E4_RESULT')
            validated=validate(raw,common['binding'],parent=parent,observer_only=role=='observer',
                               evidence_refs=common['evidence_refs'])
            (folder/'parsed.json').write_text(json.dumps(validated,indent=2))
            records.append({'call':index+1,'role':role,'parent_sha256':request['parent_sha256'],
                            'common_sha256':digest(common),'result_sha256':digest(validated)})
            parent=validated
        summary.update(status='VALID_NO_PROPOSAL' if parent['proposal'] is None else 'VALID_PROPOSAL',
                       final_proposal=parent['proposal'])
    except Exception as exc:
        summary.update(status='FAILED',error=repr(exc),final_proposal=None)
    finally:
        summary.update(calls=records,total_wall_time_s=clock()-start)
        (output/'coordination.json').write_text(json.dumps(summary,indent=2))
    return summary
