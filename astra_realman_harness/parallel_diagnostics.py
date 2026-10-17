"""Public decision summaries; original group parser still owns action semantics."""
import copy
from io_utils import strict_json
from history_diagnostics import DIAGNOSTIC_FIELDS
from parallel_arms import group_schema,parse_group


def decision_schema(states):
    return {'type':'object','additionalProperties':False,'required':['diagnostics','action'],
        'properties':{'diagnostics':{'type':'object','additionalProperties':False,
            'required':list(DIAGNOSTIC_FIELDS),'properties':{k:{'type':'string','minLength':1,'maxLength':600} for k in DIAGNOSTIC_FIELDS}},
            'action':group_schema(states)}}


def decode_decision(raw,states):
    value=strict_json(raw) if isinstance(raw,str) else copy.deepcopy(raw)
    if not isinstance(value,dict) or set(value)!={'diagnostics','action'}:raise ValueError('DECISION_ENVELOPE_FIELDS')
    d=value['diagnostics']
    if not isinstance(d,dict) or set(d)!=set(DIAGNOSTIC_FIELDS):raise ValueError('DIAGNOSTIC_FIELDS')
    if any(not isinstance(v,str) or not v.strip() or len(v)>600 for v in d.values()):raise ValueError('DIAGNOSTIC_LENGTH_OR_TYPE')
    return copy.deepcopy(d),parse_group(value['action'],states)

PUBLIC_SUMMARY_INSTRUCTION = (
    'Return diagnostics and action. In concise Chinese, summarize scene_assessment, '
    'previous_result_assessment, next_action_intent, expected_visible_change (one or two sentences each). '
    'These are public evidence summaries and predictions, not internal reasoning. '
    'State uncertainty; distinguish measured feedback from visual inference. SDK success or closed '
    'grippers does not prove grasp, handoff or placement success. First-step previous result is unknown. '
    'Action must obey the unchanged per-arm controller coordinate and action-group schema.')
