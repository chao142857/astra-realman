"""Dependency-light public chunk contract and ordered operation scheduling.

Numerical geometry/IK remain in the existing executor. This module neither
selects targets nor creates a task route.
"""
VERSION='numeric_chunk_v2_1'

def _obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def _vector(n):return {'type':'array','items':{'type':'number'},'minItems':n,'maxItems':n}

# Same anyOf/typed-enum vocabulary as the already used V1 output schema.
TCP=_obj({'arm':{'type':'string','enum':['left','right']},'kind':{'type':'string','enum':['tcp']},
    'waypoints_world_wxyz':{'type':'array','items':_vector(7),'minItems':1,'maxItems':16}})
GRIP=_obj({'arm':{'type':'string','enum':['left','right']},'kind':{'type':'string','enum':['gripper']},
    'opening_fraction':{'type':'number','minimum':0,'maximum':1},
    'contact_mode':{'type':'string','enum':['position','bilateral_hold']}})
STAGE=_obj({'mode':{'type':'string','enum':['sequential','parallel']},
    'actions':{'type':'array','items':{'anyOf':[TCP,GRIP]},'maxItems':2},
    'observe_s':{'type':'number','minimum':0,'maximum':5}})
STAGE_RULES=('sequential: actions execute in their original list order; the same arm may occur more than once, including different operation kinds. Each operation starts from measured state after its predecessor. parallel: at most one operation per arm; repeated arms are a conflict and rejected by the public semantic validator before any execution. This cross-item arm-key rule is stated here because the unchanged Bridge schema subset cannot encode uniqueness by an object property.')
STAGE['description']=STAGE_RULES
SCHEMA=_obj({'done':{'type':'boolean'},'stages':{'type':'array','items':STAGE,'maxItems':8}})

def validate_stage_semantics(stage):
    if not stage['actions'] and stage['observe_s']<=0:raise ValueError('EMPTY_STAGE_WITHOUT_OBSERVATION')
    if stage['mode']=='parallel' and len({a['arm'] for a in stage['actions']})!=len(stage['actions']):
        raise ValueError('DUPLICATE_ARM_IN_PARALLEL_STAGE')


def validate_control_semantics(value):
    if value['done'] != (len(value['stages'])==0):raise ValueError('DONE_OR_EMPTY_CHUNK')
    for stage in value['stages']:validate_stage_semantics(stage)


def stage_batches(world,stage,actual_pose,operation_nodes):
    """Sequential streams are built lazily, after prior real execution ends."""
    validate_stage_semantics(stage)
    if stage['mode']=='parallel':
        starts={a['arm']:actual_pose(world.arms[a['arm']]) for a in stage['actions']}
        streams={a['arm']:operation_nodes(a,starts[a['arm']]) for a in stage['actions']}
        indices={a['arm']:i for i,a in enumerate(stage['actions'])}
        for i in range(max((len(n) for n in streams.values()),default=0)):
            batch={side:n[i] for side,n in streams.items() if i<len(n)}
            yield batch,{side:indices[side] for side in batch},starts if i==0 else {}
    else:
        # No arm-keyed map of the actions: duplicate arm entries remain distinct.
        for index,action in enumerate(stage['actions']):
            side=action['arm'];start=actual_pose(world.arms[side])
            for i,node in enumerate(operation_nodes(action,start)):
                yield {side:node},{side:index},{side:start} if i==0 else {}

