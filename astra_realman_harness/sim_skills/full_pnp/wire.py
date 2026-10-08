"""Pure bridge projection; deliberately has NO infer() launch function or authorization."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import jsonschema


def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('DUPLICATE_JSON_KEY:'+key)
            out[key]=value
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def parse_actual_raw(raw,wire):
    """B/A actions and E selection/bbox are returned unchanged from actual raw.

    No model invocation, action synthesis, repair, or RGB stub fallback.
    """
    answer=strict_json(raw)
    jsonschema.validate(answer,schema_for_role(wire))
    if answer['binding']!=wire['binding']:raise ValueError('RAW_BINDING')
    allowed={a['id'] for a in wire['attachments']}
    if not answer['evidence_refs'] or not set(answer['evidence_refs'])<=allowed:raise ValueError('RAW_UNSEEN_REFERENCE')
    if wire['role']=='E' and answer['bbox'] is not None:
        x1,y1,x2,y2=answer['bbox']
        if not 0<=x1<x2<=1 or not 0<=y1<y2<=1:raise ValueError('RAW_ROI')
    if wire['role']!='E' and answer['parent_evidence_hash']!=wire['evidence_packet_hash']:raise ValueError('RAW_E_PARENT_HASH')
    return answer


def parse_bridge_record(record,wire):
    if record.get('error') or record.get('return_code')!=0:raise ValueError('BRIDGE_FAILED_NO_FALLBACK')
    return parse_actual_raw(record['raw'],wire)


def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def array(item):return {'type':'array','items':item}
def string():return {'type':'string'}


def schema_for_role(w):
    binding=obj({k:{'const':v,'type':'integer' if type(v) is int else 'number' if type(v) is float else 'string'} for k,v in w['binding'].items()})
    if w['role']=='E':
        return obj({'kind':{'const':'evidence','type':'string'},'binding':binding,
                    'selected_camera':{'enum':['fixed','wrist'],'type':'string'},
                    'bbox':{'anyOf':[{'type':'null'},{'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}]},
                    'claims':obj({'object_visible':string(),'identity':string(),'holding':string()}),
                    'evidence_refs':array(string()),'source':string()})
    actions={'anyOf':[obj({'type':{'const':'move_pose','type':'string'},'pose':{'type':'array','items':{'type':'number'},'minItems':7,'maxItems':7}}),
                       obj({'type':{'const':'gripper','type':'string'},'opening':{'type':'number','minimum':0,'maximum':1}}),
                       obj({'type':{'const':'hold','type':'string'},'seconds':{'type':'number','exclusiveMinimum':0,'maximum':2}})]}
    return obj({'kind':{'const':'candidate','type':'string'},'binding':binding,
                'operation':{'enum':['chunk','observe','finish','stop'],'type':'string'},
                'actions':dict(array(actions),maxItems=3),'requirements':array(string()),'evidence_refs':array(string()),
                'parent_evidence_hash':{'type':['string','null']},'verdict':{'type':['string','null']},'reason':string()})


def existing_infer_payload(input_only):
    """Exact payload shape consumed by the VERIFIED existing bridge.infer; no call made."""
    root=Path(input_only);wire=json.loads((root/'wire.json').read_text());blobs=[]
    for image in wire['attachments']:
        name=image['file']
        if Path(name).name!=name:raise ValueError('ATTACHMENT_PATH_ESCAPE')
        data=(root/name).read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=image['sha256']:raise ValueError('ATTACHMENT_HASH')
        blobs.append(base64.b64encode(data).decode())
    if not 1<=len(blobs)<=4:raise ValueError('IMAGE_COUNT')
    return {'context':copy.deepcopy(wire),'images':blobs,'schema':schema_for_role(wire)}
