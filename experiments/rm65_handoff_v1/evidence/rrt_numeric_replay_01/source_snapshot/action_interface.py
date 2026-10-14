"""Numeric simulation contract; no hardware import and no automatic task skills."""
import copy,hashlib,importlib.util,json,sys
from pathlib import Path
import jsonschema
ROOT=Path(__file__).resolve().parents[2]
V0=ROOT/'experiments/spatial_input_eval_v0'
sys.path.insert(0,str(V0));sys.path.insert(0,str(V0/'lab'))
from spatial_eval.schema import strict_json
from spatial_eval.mac_bridge import MacBridgeConfig
from pilot02_runtime import bridge_module

def full_command_audit(command):
 try:
  inp=Path(command[command.index("--cd")+1])
  return inp.name=="input_only" and command==bridge_module().command(inp.parent,[inp/f"image-{i}.png" for i in range(4)])
 except (ValueError,IndexError,TypeError):return False

def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def vector(n):return {'type':'array','items':{'type':'number'},'minItems':n,'maxItems':n}
ACTION=obj({'arm':{'type':'string','enum':['left','right']},'kind':{'type':'string','enum':['tcp','gripper']},'pose_world_wxyz':{'anyOf':[vector(7),{'type':'null'}]},'opening_fraction':{'anyOf':[{'type':'number','minimum':0,'maximum':1},{'type':'null'}]}})
SCHEMA=obj({'done':{'type':'boolean'},'execution':{'type':'string','enum':['sequential','parallel']},'actions':{'type':'array','items':ACTION,'maxItems':2}})
INSTRUCTION='把左臂持有的红色方块交给右臂，再由右臂放到蓝色目标区域。仅输出所给 schema 的 JSON。自主决定交接位置、接近方式和夹爪时机。未指定机械臂保持。done=true 只表示你决定停止，不代表评测成功。'
CONVENTIONS={'position':'metres, shared SAPIEN world','quaternion':'unit quaternion [w,x,y,z], Link6 orientation in world','tcp':'mean of the actual two inner pad face centres; offset depends on measured gripper configuration','opening_fraction':'0 closed command, 1 open command; measured gap is actual_pad_gap_m, not this command','execution':'one tcp OR gripper operation per named arm. sequential follows list order. parallel overlaps both operations in shared physics steps. Omitted arm holds drive targets. No automatic obstacle rerouting or target correction.','time':'physics paused during inference; execution advances physics. Not real-time asynchronous control.'}

def parse_action(raw):
 value=strict_json(raw);jsonschema.validate(value,SCHEMA)
 if len({a['arm'] for a in value['actions']})!=len(value['actions']):raise ValueError('DUPLICATE_ARM')
 if value['done'] and value['actions']:raise ValueError('DONE_WITH_ACTIONS')
 if not value['done'] and not value['actions']:raise ValueError('EMPTY_GROUP')
 for a in value['actions']:
  if a['kind']=='tcp':
   if a['pose_world_wxyz'] is None or a['opening_fraction'] is not None:raise ValueError('TCP_FIELDS')
   q=a['pose_world_wxyz'][3:]
   if abs(sum(x*x for x in q)-1)>.002:raise ValueError('QUATERNION_NORM')
  elif a['pose_world_wxyz'] is not None or a['opening_fraction'] is None:raise ValueError('GRIPPER_FIELDS')
 return value

def context_from_observation(obs,history):
 # Explicit allowlist; no Scene, cube pose, contact GT, witness or expert actions.
 context={'instruction':INSTRUCTION,'conventions':CONVENTIONS,'output_schema':SCHEMA,'observations':{k:copy.deepcopy(obs[k]) for k in ['calibration','arms','sim_time_s','base_transforms_world_wxyz']},'recent_history':copy.deepcopy(history[-2:]),'attachments':[]}
 images=[Path(p) for p in obs['images']]
 for i,(camera,path) in enumerate(zip(['overhead','tabletop_front','left_wrist','right_wrist'],images)):
  context['attachments'].append({'camera_id':camera,'file':f'image-{i}.png','sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 validate_context(context,images);return context,images

def validate_context(c,images):
 if set(c)!={'instruction','conventions','output_schema','observations','recent_history','attachments'}:raise ValueError('PUBLIC_FIELDS')
 if c['instruction']!=INSTRUCTION or c['conventions']!=CONVENTIONS or c['output_schema']!=SCHEMA:raise ValueError('CONTRACT_CHANGED')
 if set(c['observations'])!={'calibration','arms','sim_time_s','base_transforms_world_wxyz'}:raise ValueError('OBSERVATION_FIELDS')
 if len(images)!=4 or len(c['attachments'])!=4:raise ValueError('FOUR_RGB_REQUIRED')
 if len(c['recent_history'])>2:raise ValueError('HISTORY_BOUND')
 for row in c['recent_history']:
  if set(row)!={'proposal','receipt'}:raise ValueError('HISTORY_FIELDS')
  parse_action(json.dumps(row['proposal'],allow_nan=False))
 if [x['camera_id'] for x in c['attachments']]!=['overhead','tabletop_front','left_wrist','right_wrist']:raise ValueError('CAMERA_ROLES')
 for i,(item,path) in enumerate(zip(c['attachments'],images)):
  if item['file']!=f'image-{i}.png':raise ValueError('ATTACHMENT_ORDER')
  if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('IMAGE_HASH')
 # No recursive scene/GT dictionaries may enter even through feedback.
 def walk(x):
  if isinstance(x,dict):
   for k,v in x.items():
    if k.lower() in {'ground_truth','oracle','witness','object_pose','object_velocity','contacts','expert_trajectory','target_grasp'}:raise ValueError('PRIVATE_FIELD:'+k)
    walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(c)

spec=importlib.util.spec_from_file_location('spatial_eval._rm65_transport',V0/'spatial_eval/mac_bridge.py');transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport);transport.validate_context=validate_context;transport.parameter_audit=lambda result:full_command_audit(result.get("command"))
class HandoffBridgeAdapter(transport.MacBridgeAdapter):
 def __init__(self,config,*,offline_test=True):
  if not offline_test:raise ValueError('PHYSICAL_BASELINE_AND_NEW_AUTHORIZATION_REQUIRED')
  super().__init__(config,offline_test=True,timeout_limit_s=180)
 def infer(self,context,images,folder,*,real=False,timeout_s=180):
  if real:raise ValueError('THIS_STAGE_GENERATION_BUDGET_ZERO')
  return super().infer(context,images,folder,real=False,timeout_s=timeout_s)

def accept_result(folder):
 p=Path(folder);r=json.loads((p/'response.json').read_text());t=json.loads((p/'transport.json').read_text());original=json.loads((p/'bridge_result.json').read_text())
 if r['raw']!=original.get('raw') or r['events']!=original.get('events') or (p/'raw.txt').read_text()!=r['raw'] or (p/'events.jsonl').read_text()!=r['events']:raise ValueError('ARCHIVE_INCONSISTENT')
 if r['error'] is not None or r['return_code']!=0 or t.get('http_status')!=200 or t.get('cancel_attempts')!=0:raise ValueError('INFRASTRUCTURE_FAILURE')
 if t.get('remote_model_parameter_audit')!='PASS' or not full_command_audit(original.get('command')):raise ValueError('PARAMETER_DRIFT')
 events=[strict_json(s) for s in r['events'].splitlines() if s.strip()]
 if sum(e.get('type')=='turn.completed' for e in events)!=1 or sum(e.get('type')=='thread.started' for e in events)!=1:raise ValueError('COMPLETION_UNKNOWN')
 if any(e.get('type') in ['error','turn.failed'] for e in events) or 'reconnect' in (r['events']+r['stderr']).lower():raise ValueError('CLI_ERROR_OR_RECONNECT')
 return parse_action(r['raw'])

def execute_action(world,value):
 value=parse_action(json.dumps(value,allow_nan=False))
 if value['done']:return {'ok':True,'executed':False,'reason':'MODEL_STOP_REQUEST'}
 def commands(actions):return {a['arm']:({'pose':a['pose_world_wxyz']} if a['kind']=='tcp' else {'opening':a['opening_fraction']}) for a in actions}
 if value['execution']=='parallel':return world.execute_group(commands(value['actions']))
 receipts=[]
 for a in value['actions']:
  receipt=world.execute_group(commands([a]));receipts.append(receipt)
  if not receipt['ok']:break
 return {'ok':all(r['ok'] for r in receipts),'executed':any(r.get('executed') for r in receipts),'mode':'sequential','receipts':receipts}
