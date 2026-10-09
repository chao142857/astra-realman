"""Join frozen RGB semantic hypotheses to learned depth surface support.

Bboxes select support; they are NEVER corresponding 3D points or object centers.
No semantic or geometric estimate grants physical task admission.
"""
import math
import numpy as np
import jsonschema
from sim_skills.full_pnp.wire import obj
from .contracts import clone, digest

def semantic_schema():
    s={'type':'string','minLength':1}
    region=obj({'attachment_id':s, 'bbox':{'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':4,'maxItems':4},
        'visibility':{'type': 'string', 'enum':['visible','partial','unknown']}})
    entity=obj({'entity_id':s,'label':s,'kind':{'type': 'string', 'enum':['object','region','unknown']},
        'identity_status':{'type': 'string', 'enum':['hypothesis','unknown']},
        'views':{'type':'array','items':region,'maxItems':3}, 'description':{'type':'string'}})
    relation=obj({'subject':s,'predicate':{'type': 'string', 'enum':['left_of','right_of','above','on','near','target_of','unknown']},
        'object':s,'status':{'type': 'string', 'enum':['hypothesis','unknown']},
        'evidence_refs':{'type':'array','items':s,'minItems':1}})
    return obj({'version':{'type':'string','const':'astra.semantic_scene.v2'},
        'task_target_id':{'type':['string','null']},
        'entities':{'type':'array','items':entity,'minItems':1,'maxItems':24},
        'relations':{'type':'array','items':relation,'maxItems':48},
        'unknowns':{'type':'array','items':s,'maxItems':32}})

def fuse(store, geometry_request, semantic_evidence_id):
    if geometry_request['status']!='READY': raise ValueError('GEOMETRY_NOT_READY')
    geom=geometry_request['result']; state=geom['state']; b=geom['binding']
    if state['backend']!='da3_small_v1': raise ValueError('LEARNED_GEOMETRY_REQUIRED')
    e=store.get_evidence(semantic_evidence_id)
    if e['role']!='semantic_e0': raise ValueError('INITIAL_SEMANTIC_ROLE_REQUIRED')
    jsonschema.validate(e['result'],semantic_schema())
    oid=state['observation_id']; obs=store.get(oid)
    if e['observation_ids']!=[oid] or b['observation_ids']!=[oid]: raise ValueError('FROZEN_INPUT_MISMATCH')
    if geom.get('world_revision')!=store.revision: raise ValueError('STALE_FUSION_BASE')
    attachments={a['id']:a for a in e['attachments']}
    if {a['camera'] for a in attachments.values()}!={'assembly','fixed','wrist'}:
        raise ValueError('E0_REQUIRES_THREE_VIEWS')
    for a in attachments.values():
        _,source=store.image(oid,a['camera'])
        if a['source_sha256']!=source['sha256'] or a['transform']['crop_xyxy_pixels'] is not None:
            raise ValueError('E0_FULL_FROZEN_RGB_REQUIRED')
    entities={}
    for semantic in e['result']['entities']:
        identity=semantic['entity_id']
        if identity in entities: raise ValueError('DUPLICATE_INSTANCE_ID')
        support=[]; views=[]; points_by_view=[]
        for v in semantic['views']:
            if v['attachment_id'] not in attachments: raise ValueError('UNSEEN_SEMANTIC_VIEW')
            a=attachments[v['attachment_id']]; x0,y0,x1,y1=v['bbox']
            if not 0<=x0<x1<=1 or not 0<=y0<y1<=1: raise ValueError('REGION_BBOX')
            if a['camera'] in [x['camera'] for x in views]: raise ValueError('DUPLICATE_ENTITY_VIEW')
            width,height=a['transform']['source_resolution']
            views.append({'camera':a['camera'],'bbox':v['bbox'],'visibility':v['visibility'],
                          'attachment_id':a['id'],'observation_id':oid})
            if v['visibility']!='visible' or x0==0 or y0==0 or x1==1 or y1==1: continue
            selected=[p for p in state['surface_samples'] if p['camera']==a['camera'] and
                x0*width<=p['pixel'][0]<=x1*width and y0*height<=p['pixel'][1]<=y1*height]
            if len(selected)<4: continue
            support.extend(selected);points_by_view.append(np.median([p['point_world_m'] for p in selected],axis=0))
        point=None;radius=None;status='unknown';reason='INSUFFICIENT_UNCLIPPED_MULTIVIEW_DEPTH_SUPPORT'
        if len(points_by_view)>=2 and semantic['identity_status']=='hypothesis':
            pts=np.array([p['point_world_m'] for p in support]);center=np.median(pts,axis=0)
            disagreement=max(np.linalg.norm(v-center) for v in points_by_view)
            spread=float(np.quantile(np.linalg.norm(pts-center,axis=1),.9))
            if disagreement<=.05 and spread<=.12:
                point=center.tolist();radius=max(.02,spread,float(disagreement))
                status='coarse';reason='DEPTH_REGION_SURFACE_SUPPORT_NOT_OBJECT_CENTER'
            else: reason='REGION_DEPTH_INCONSISTENT_OR_BACKGROUND_MIXED'
        entities[identity]={'label':semantic['label'],'kind':semantic['kind'],
            'identity_status':semantic['identity_status'],'status':status,'point_world_m':point,
            'uncertainty_radius_m':radius,'uncertainty_semantics':'uncalibrated surface extent and view disagreement; not probability',
            'visibility':{v['camera']:v['visibility'] for v in views}, 'motion':'unknown',
            'held_relation':'unknown','measurement_kind':'current_depth_region' if status=='coarse' else 'unknown',
            'semantic_evidence_id':semantic_evidence_id, 'views':views, 'reason':reason}
    for r in e['result']['relations']:
        if r['subject'] not in entities or r['object'] not in entities or not set(r['evidence_refs'])<=set(attachments):
            raise ValueError('UNBOUND_SEMANTIC_RELATION')
    target=e['result']['task_target_id']
    if target is not None and target not in entities: raise ValueError('TASK_TARGET_NOT_AN_ENTITY')
    quality=state.get('geometry_quality',{'numeric_valid':'unknown','self_consistent':'unknown',
        'task_usable':'unknown','observation_id':oid,'reason':['UNASSESSED_GEOMETRY']})
    if quality.get('self_consistent')!='pass':
        for entity in entities.values():
            entity['rejected_geometry']={'point_world_m':entity['point_world_m'],'reason':'GEOMETRY_NOT_SELF_CONSISTENT'}
            entity.update(status='unknown',point_world_m=None,uncertainty_radius_m=None,measurement_kind='unknown')
    report={**clone(state),'backend':'semantic_lwh_v1','geometry_backend':'da3_small_v1',
        'geometry_only':False,'task_identity_verified':False,'entities':entities,
        'relations':clone(e['result']['relations']),'unknowns':clone(e['result']['unknowns']),
        'semantic_evidence_id':semantic_evidence_id, 'geometry_world_id':geom['world_id']}
    report['geometry_quality']=clone(quality)
    report['task_target_id']=target
    # Intrinsics/rig contract stays fixed; wrist extrinsics are measured each observation.
    from .model_context import calibration_key
    deps={'semantic/'+semantic_evidence_id:1,'task_scope/coarse_precontact_v1':1,
          calibration_key(obs['calibration']):1}
    binding={**clone(b),'evidence_ids':[semantic_evidence_id], 'geometry_world_id':geom['world_id']}
    provenance='FAKE_MODEL_RAW' if 'FAKE_MODEL_RAW' in (geom['provenance'],e['provenance']) else e['provenance']
    return store.publish_world(report,binding,provenance,read_versions=deps)

def current_regions(reference, geometry):
    """Cheap current depth support under projected old regions is NOT re-identification.

    Until a current association/tracker is validated, unknown is the correct update.
    This prevents a stale box/point prediction becoming a current measurement.
    """
    out=clone(geometry)
    out['entities']={i:{**clone(e),'status':'unknown','point_world_m':None,'uncertainty_radius_m':None,
        'measurement_kind':'unknown','visibility':{},'motion':'unknown',
        'reason':'CURRENT_INSTANCE_ASSOCIATION_NOT_VERIFIED',
        'historical_geometry':{'point_world_m':e['point_world_m'],'observation_id':reference['observation_id']}}
        for i,e in reference['entities'].items()}
    return out
