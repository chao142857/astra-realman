"""Strict high-level decisions; independent from old eight-field action schema."""
import copy,json,math
from io_utils import strict_json

ACTIONS=('OBSERVE','SELECT_OBJECT','LEFT_PICK','LEFT_PRESENT','BIMANUAL_HANDOFF','RIGHT_PLACE','VERIFY','RECOVER','DELTA_CORRECTION')
DESTINATIONS={'fruit':'plate','clutter':'box'}
STAGES=('unprocessed','left_grasped','handoff_ready','right_grasped','sorting','placed','failed')
class Rejected(ValueError):pass
class HardwareDisabled(RuntimeError):pass
class SkillFailure(RuntimeError):pass

def require(ok,why):
    if not ok:raise Rejected(why)

def finite_vector(v,n):return isinstance(v,list) and len(v)==n and all(type(x)in(int,float) and math.isfinite(x) for x in v)

def parse(raw):
    a=strict_json(raw) if isinstance(raw,str) else copy.deepcopy(raw)
    fields={'schema_version','operation_id','state_version','revision','action','object_id','semantic_class','destination','arm_id','frame','translation_m','rotation_rpy_rad','intent'}
    require(isinstance(a,dict) and set(a)==fields,'ACTION_FIELDS')
    require(type(a['schema_version']) is int and a['schema_version']==1 and a['action'] in ACTIONS,'ACTION_VERSION_OR_KIND')
    require(isinstance(a['operation_id'],str) and 0<len(a['operation_id'])<=128,'OPERATION_ID')
    require(type(a['state_version'])is int and a['state_version']>=0,'STATE_VERSION')
    require(isinstance(a['revision'],dict) and set(a['revision'])=={'camera','layout','calibration'},'REVISION')
    require(all(isinstance(x,str) and x for x in a['revision'].values()),'REVISION_VALUES')
    require(a['object_id'] is None or isinstance(a['object_id'],str) and 0<len(a['object_id'])<=128,'OBJECT_ID')
    require(a['semantic_class'] in (None,'fruit','clutter') and a['destination'] in (None,'plate','box'),'CLASS_OR_DESTINATION')
    require(a['arm_id'] in (None,'left','right'),'ARM_ID')
    require(a['frame'] is None or isinstance(a['frame'],str) and a['frame'],'FRAME')
    require(finite_vector(a['translation_m'],3) and finite_vector(a['rotation_rpy_rad'],3),'FINITE_DELTA')
    require(isinstance(a['intent'],str) and 0<len(a['intent'])<=600,'SHORT_INTENT')
    if a['action']=='OBSERVE':require(a['object_id'] is None,'OBSERVE_GLOBAL')
    else:require(a['object_id'] is not None,'OBJECT_REQUIRED')
    if a['action']=='SELECT_OBJECT':require(a['semantic_class'] in DESTINATIONS and a['destination']==DESTINATIONS[a['semantic_class']],'DESTINATION_RULE')
    elif a['action']=='RIGHT_PLACE':require(a['destination'] in ('plate','box') and a['semantic_class'] is None,'PLACE_DESTINATION')
    else:require(a['semantic_class'] is None and a['destination'] is None,'UNUSED_CLASS_FIELDS')
    if a['action']=='DELTA_CORRECTION':require(a['arm_id'] and a['frame'],'DELTA_ARM_FRAME')
    else:require(a['arm_id'] is None and a['frame'] is None and not any(a['translation_m']+a['rotation_rpy_rad']),'HIGH_LEVEL_NOT_DELTA')
    return a

def action(state,kind,object_id=None,**kwargs):
    """Synthetic decision helper, not an autonomous decision backend."""
    a={'schema_version':1,'operation_id':__import__('uuid').uuid4().hex,'state_version':state.version,
       'revision':copy.deepcopy(state.revision),'action':kind,'object_id':object_id,'semantic_class':None,
       'destination':None,'arm_id':None,'frame':None,'translation_m':[0,0,0],'rotation_rpy_rad':[0,0,0],
       'intent':'SCRIPTED_SYNTHETIC_DECISION; not real Astra output.'}
    a.update(kwargs);return parse(a)

class DisabledAstraBackend:
    def decide(self,context,images):raise RuntimeError('REAL_MODEL_DISABLED_IN_FOUNDATION')
