"""Bind sealed real semantic hypotheses to unchanged geometry in the existing Store.

Archive roots/pins are trusted host configuration, never model arguments. Hashes
protect frozen evidence; they do not authenticate arbitrary host code. No model,
geometry recomputation, execution or second estimator is implemented here.
"""
import hashlib
import json
from pathlib import Path
import jsonschema
from sim_skills.full_pnp.wire import strict_json
from scripts.structured_outputs import encoded, validate_local
from .contracts import clone, digest

VERSION = 'astra.persistent_semantic_binding.v1'
PROVENANCE = 'COMPOSITE_PUBLIC_RGBD_AND_MODEL_RAW'
SEMANTIC_FIELDS = ('semantic_category', 'semantic_attributes', 'semantic_disposition',
                   'semantic_status', 'semantic_evidence_id', 'semantic_source')

def _require(test, reason):
    if not test: raise ValueError(reason)

def _sha(data): return hashlib.sha256(data).hexdigest()

def verify_world_hash(world):
    _require(world['world_id'] == 'w-' + digest({k:v for k,v in world.items() if k!='world_id'}), 'WORLD_CONTENT_HASH')

def import_grounding_archive(store, archive, manifest_sha256, world_id, evidence_id):
    """Register a trusted receipt from an externally pinned, sealed real attempt.

    Read only required public/model artifacts. Do not open reviews, GT, depth,
    private layouts or credentials. The caller MUST supply the frozen manifest pin.
    """
    root = Path(archive).resolve()
    manifest_bytes = (root/'DELIVERY_MANIFEST.json').read_bytes()
    _require(_sha(manifest_bytes) == manifest_sha256, 'ARCHIVE_MANIFEST_PIN')
    manifest = strict_json(manifest_bytes)
    def data(rel):
        p = (root/rel).resolve()
        _require(p.is_relative_to(root) and rel in manifest, 'ARCHIVE_FILE_NOT_PINNED')
        b = p.read_bytes(); _require(_sha(b)==manifest[rel], 'ARCHIVE_FILE_HASH:'+rel)
        return b
    def read(rel): return strict_json(data(rel))
    seal = read('MODEL_RESULT_SEAL.json')
    evidence = read(evidence_id+'.json'); row = read('broker/broker-001/attempt.json')
    wire_bytes = data('broker/broker-001/input_only/wire.json'); wire = strict_json(wire_bytes)
    raw = read('RAW_RESPONSE.json')['raw']; parsed = read('PARSED_RESPONSE.json')['parsed']
    model = read('MODEL_RESULT.json'); audit = read('PROVENANCE_AUDIT.json')
    request = read('REQUEST.json')
    _require(seal['sealed_before_independent_review'] is True, 'UNSEALED_MODEL_RESULT')
    for rel in ('broker/broker-001/attempt.json', 'broker/broker-001/input_only/wire.json',
                'RAW_RESPONSE.json', 'PARSED_RESPONSE.json', 'MODEL_RESULT.json', evidence_id+'.json'):
        _require(seal['files'].get(rel)==manifest[rel], 'MODEL_SEAL_MEMBERSHIP')
    _require(model['status']=='READY' and model['broker_submissions']==1 and model['infer_started_count']==1,
             'REAL_ATTEMPT_NOT_READY')
    _require(row['status']=='READY' and row['role']=='semantic_grounding' and row['provenance']=='MODEL_RAW'
             and row.get('error') is None, 'REAL_GROUNDING_RAW_REQUIRED')
    _require(evidence['provenance']=='MODEL_RAW' and evidence['role']=='semantic_grounding', 'EVIDENCE_PROVENANCE')
    _require(evidence_id==evidence['evidence_id']=='e-'+digest({k:v for k,v in evidence.items() if k!='evidence_id'}), 'EVIDENCE_CONTENT_HASH')
    _require(row['evidence_id']==model['evidence_id']==evidence_id, 'EVIDENCE_REQUEST_JOIN')
    _require(raw and raw==row['raw']==row['worker_record']['raw'] and strict_json(raw)==parsed==row['parsed'], 'RAW_PARSED_MISMATCH')
    _require(_sha(raw.encode())==audit['raw_utf8_sha256'], 'RAW_HASH')
    raw_paths=[p for p,h in seal['files'].items() if p.endswith('/last_message.json')]
    _require(len(raw_paths)==1 and data(raw_paths[0]).decode()==raw, 'ORIGINAL_CLI_RAW')
    world=store.get_world(world_id); verify_world_hash(world)
    _require(world['provenance']=='PUBLIC_RGBD_MEASUREMENT' and world['state'].get('initialization')=='geometry_first_v2'
             and not world['binding'].get('evidence_ids') and not world['state'].get('semantic_binding_version'), 'GEOMETRY_ONLY_BASE_REQUIRED')
    obs=store.get(world['state']['observation_id']); oid=obs['observation_id']
    expected_binding={'episode_id':store.episode_id,'request_id':row['request_id'],
        'execution_epoch':obs['execution_epoch'],'world_id':world_id,'world_revision':world['world_revision'],
        'observation_ids':[oid],'evidence_ids':[]}
    _require(row['binding']==wire['binding']==expected_binding, 'GROUNDING_WORLD_BINDING')
    _require(evidence['request_id']==row['request_id'] and evidence['observation_ids']==[oid], 'EVIDENCE_OBSERVATION')
    _require(world['binding']['execution_epoch']==obs['execution_epoch'], 'GEOMETRY_EPOCH')
    from .model_context import role_world_view, observation_view
    from .review_contracts import validate_review_request, grounding_schema
    from .broker import output_contract
    from .output_validation import validate_role
    validate_review_request(request,world,obs)
    _require(wire['role']=='semantic_grounding' and wire['evidence']==[] and wire['instruction']==request['instruction'], 'GROUNDING_WIRE')
    _require(wire['WorldSnapshot']==role_world_view(store,world_id,'semantic_grounding'), 'GROUNDING_WORLD_QUERY')
    _require(wire['observations']=={oid:observation_view(obs,'semantic_grounding')}, 'GROUNDING_OBSERVATION_VIEW')
    attachments=wire['attachments']
    _require(len(attachments)==3 and {a['camera'] for a in attachments}=={'assembly','fixed','wrist'}, 'THREE_GROUNDING_VIEWS')
    _require(row['attachments']==evidence['attachments']==attachments, 'EVIDENCE_ATTACHMENTS')
    for a in attachments:
        pixels, meta=store.image(oid,a['camera'])
        _require(a['sha256']==a['source_sha256']==meta['sha256']==_sha(pixels), 'GROUNDING_RGB_HASH')
        _require(a['id']==oid+':'+a['camera']+':'+a['sha256'] and a['observation_id']==oid
                 and a['execution_epoch']==obs['execution_epoch'] and a['captured_monotonic']==obs['captured_monotonic'], 'GROUNDING_IMAGE_BINDING')
        _require(a['transform']['crop_xyxy_pixels'] is None and a['selected_intrinsic']==obs['calibration'][a['camera']]['intrinsic'], 'GROUNDING_IMAGE_GEOMETRY')
    local,provider,_=output_contract(grounding_schema(world),expected_binding,[a['id'] for a in attachments],[],echo_binding=False)
    _require(row['schema']==row['authoritative_schema']==local and row['provider_schema']==provider, 'GROUNDING_SCHEMA_CONTRACT')
    _require(data('PROVIDER_SCHEMA.json')==encoded(provider) and data('AUTHORITATIVE_SCHEMA.json')==encoded(local), 'GROUNDING_SCHEMA_HASH')
    _require(row['wire_sha256']==_sha(wire_bytes)==audit['input_wire_sha256'], 'GROUNDING_WIRE_HASH')
    validate_local(parsed,local,provider);validate_role('semantic_grounding',parsed['result'],attachments,expected_binding,world)
    _require(evidence['result']==parsed['result'] and evidence.get('grants_execution') is False and evidence.get('execution_class')=='REVIEW_ONLY', 'GROUNDING_RESULT_JOIN')
    receipt={'version':VERSION,'evidence_id':evidence_id,'evidence_content_sha256':digest(evidence),
        'raw_sha256':_sha(raw.encode()),'provider_schema_sha256':_sha(encoded(provider)),
        'authoritative_schema_sha256':_sha(encoded(local)),'wire_sha256':_sha(wire_bytes),
        'archive_manifest_sha256':manifest_sha256,'model_result_seal_sha256':manifest['MODEL_RESULT_SEAL.json'],
        'qualified_request_id':model['qualified_request_id'],'binding':expected_binding,
        'geometry_state_sha256':digest(world['state']),'read_versions':clone(world['read_versions']),
        'observation_sha256':digest(obs),'task_instruction':wire['instruction'],
        'provenance':'MODEL_RAW','verification':'PINNED_ARCHIVE_RAW_SCHEMA_AND_BINDINGS', 'grants_execution':False}
    receipt['source_id']='source-'+digest(receipt)
    if evidence_id in store.evidence: _require(store.get_evidence(evidence_id)==evidence, 'IMMUTABLE_EVIDENCE')
    if evidence_id in store.grounding_sources: _require(store.grounding_sources[evidence_id]==receipt, 'IMMUTABLE_SOURCE_RECEIPT')
    store.evidence[evidence_id]=clone(evidence);store.grounding_sources[evidence_id]=clone(receipt)
    return clone(receipt)

def _source(store, base, evidence_id):
    verify_world_hash(base)
    _require(evidence_id in store.grounding_sources, 'VERIFIED_GROUNDING_RECEIPT_REQUIRED')
    source=clone(store.grounding_sources[evidence_id]);e=store.get_evidence(evidence_id)
    _require(source['source_id']=='source-'+digest({k:v for k,v in source.items() if k!='source_id'}), 'SOURCE_RECEIPT_HASH')
    _require(source['provenance']==e['provenance']=='MODEL_RAW' and e['role']=='semantic_grounding', 'REAL_GROUNDING_SOURCE_REQUIRED')
    _require(e['evidence_id']=='e-'+digest({k:v for k,v in e.items() if k!='evidence_id'}) and digest(e)==source['evidence_content_sha256'], 'EVIDENCE_RECEIPT_MISMATCH')
    obs=store.get(base['state']['observation_id'])
    _require(source['binding']['world_id']==base['world_id'] and source['binding']['world_revision']==base['world_revision']
             and source['geometry_state_sha256']==digest(base['state']) and source['read_versions']==base['read_versions'], 'SOURCE_WORLD_CHANGED')
    _require(source['observation_sha256']==digest(obs) and source['binding']['execution_epoch']==obs['execution_epoch'], 'SOURCE_OBSERVATION_CHANGED')
    for a in e['attachments']:
        pixels,meta=store.image(obs['observation_id'],a['camera'])
        _require(_sha(pixels)==a['sha256']==meta['sha256'], 'SOURCE_IMAGE_CHANGED')
    return e,source

def _bound_parts(store,base,evidence_id,task):
    from .chunk_plan import plan_schema
    jsonschema.validate(task,plan_schema()['properties']['task'])
    e,source=_source(store,base,evidence_id);answer=e['result'];state=clone(base['state'])
    for item in answer['objects']:
        entity=state['entities'][item['geometry_instance_id']]
        entity.update(semantic_category=item['category'],semantic_attributes=clone(item['attributes']),
            semantic_disposition=item['disposition'],semantic_status=item['semantic_status'],
            semantic_evidence_id=evidence_id,semantic_source={'source_id':source['source_id'],
                'provenance':'MODEL_RAW','raw_sha256':source['raw_sha256'],'evidence_refs':clone(item['evidence_refs'])})
    selection={'task':clone(task),'task_target_geometry_id':answer['task_target_geometry_id'],
        'status':answer['target_status'],'evidence_id':evidence_id,'instruction':source['task_instruction'],
        'support':'MODEL_HYPOTHESIS_WITH_BOUND_GEOMETRY_NOT_PHYSICAL_CERTIFICATION','grants_execution':False}
    state.update(semantic_binding_version=VERSION,geometry_only=False,task_identity_verified=False,
        task_target_id=answer['task_target_geometry_id'],task_target_geometry_id=answer['task_target_geometry_id'],
        task_selection=selection,semantic_evidence_id=evidence_id,semantic_source=source,
        semantic_unknowns=clone(answer['unknowns']),semantic_requests=clone(answer['requests']),
        geometry_provenance={'provenance':base['provenance'],'world_id':base['world_id'],
            'world_revision':base['world_revision'],'state_sha256':digest(base['state']),'measurements_unchanged':True},
        semantic_provenance={'provenance':'MODEL_RAW','evidence_id':evidence_id,'source_id':source['source_id'],
            'raw_sha256':source['raw_sha256'],'identity_status':'hypothesis_not_ground_truth'})
    # Preserve geometric unknowns, surfaces (including robot), quality, timestamps,
    # bounds and tracking arrays. Semantic requests remain unexecuted data.
    deps={**clone(base['read_versions']),'semantic/'+evidence_id:1,
          'semantic_binding/'+VERSION:1,'task_selection/'+digest(selection):1}
    binding={**clone(base['binding']),'world_revision':base['world_revision'],
        'geometry_world_id':base['world_id'],'evidence_ids':[evidence_id],
        'semantic_source_id':source['source_id'],'semantic_raw_sha256':source['raw_sha256']}
    return state,binding,deps

def bind_grounding(store,world_id,evidence_id,task):
    base=store.get_world(world_id)
    _require(store.current_world_id==world_id and store.revision==base['world_revision'] and store.read_versions==base['read_versions'], 'STALE_SEMANTIC_BINDING_BASE')
    _require(not base['state'].get('semantic_binding_version'), 'GEOMETRY_ONLY_BASE_REQUIRED')
    state,binding,deps=_bound_parts(store,base,evidence_id,task)
    world=store.publish_world(state,binding,PROVENANCE,read_versions=deps)
    store.semantic_world_pins[world['world_id']]=clone(task)
    return world

def restore_persistent_world(store,world,world_id_pin,task_pin):
    """Reload a frozen publication using trusted host pins, never model-provided pins."""
    _require(world['world_id']==world_id_pin, 'RESTORE_WORLD_PIN')
    verify_world_hash(world)
    _require(world['provenance']==PROVENANCE and world['state']['task_selection']['task']==task_pin, 'RESTORE_TASK_PIN')
    base=store.get_world(world['binding']['geometry_world_id'])
    _require(store.current_world_id in (base['world_id'],world_id_pin), 'RESTORE_CURRENT_WORLD')
    eids=world['binding']['evidence_ids'];_require(len(eids)==1,'RESTORE_EVIDENCE')
    state,binding,deps=_bound_parts(store,base,eids[0],task_pin)
    _require(world['state']==state and world['binding']==binding and world['read_versions']==deps
             and world['world_revision']==base['world_revision']+1, 'RESTORE_CONTENT_MISMATCH')
    if world_id_pin in store.worlds: _require(store.worlds[world_id_pin]==world,'IMMUTABLE_WORLD')
    store.worlds[world_id_pin]=clone(world);store.current_world_id=world_id_pin
    store.revision=world['world_revision'];store.read_versions=clone(deps)
    store.semantic_world_pins[world_id_pin]=clone(task_pin)
    return clone(world)

def requires_binding_check(store,world):
    return bool(world['state'].get('semantic_binding_version') or world['provenance']==PROVENANCE
        or any(store.get_evidence(i)['role']=='semantic_grounding' for i in world['binding'].get('evidence_ids',[])))

def validate_persistent_world(store,world,require_current=True):
    if world['state'].get('geometry_update_version'):
        return validate_geometry_update(store,world,require_current)
    verify_world_hash(world)
    _require(world['world_id'] in store.semantic_world_pins
             and store.semantic_world_pins[world['world_id']]==world['state']['task_selection']['task'], 'PUBLISHED_WORLD_TASK_PIN')
    _require(world['provenance']==PROVENANCE and world['state'].get('semantic_binding_version')==VERSION, 'PERSISTENT_PROVENANCE')
    eids=world['binding'].get('evidence_ids',[]);_require(len(eids)==1, 'PERSISTENT_EVIDENCE_BINDING')
    base=store.get_world(world['binding']['geometry_world_id'])
    state,binding,deps=_bound_parts(store,base,eids[0],world['state']['task_selection']['task'])
    _require(world['state']==state and world['binding']==binding and world['read_versions']==deps
             and world['world_revision']==base['world_revision']+1, 'PERSISTENT_WORLD_MISMATCH')
    if require_current:
        _require(store.current_world_id==world['world_id'] and store.revision==world['world_revision']
                 and store.read_versions==deps, 'STALE_PERSISTENT_WORLD')
    return True

def register_geometry_update(store,world,parent,observation):
    """Trusted WorldHead publication receipt, not a model-asserted provenance."""
    receipt={'world_sha256':digest(world),'parent_world_id':parent['world_id'],
        'parent_sha256':digest(parent),'observation_id':observation['observation_id'],
        'observation_sha256':digest(observation),'read_versions':clone(world['read_versions']),
        'measurement_source':'CURRENT_HASH_VERIFIED_RGBD_WITH_MEASURED_FK',
        'semantic_source':'PRIOR_BOUND_EVIDENCE_ONLY_VIA_TEMPORAL_ASSOCIATION','grants_execution':False}
    store.geometry_update_receipts[world['world_id']]=receipt
    if parent['world_id'] in store.semantic_world_pins:
        store.semantic_world_pins[world['world_id']]=clone(store.semantic_world_pins[parent['world_id']])

def _validate_geometry_update(store,world,require_current=True,full_audit=False):
    verify_world_hash(world)
    _require(store.get_world(world['world_id'])==world,'PUBLISHED_WORLD_MISMATCH')
    receipt=store.geometry_update_receipts.get(world['world_id'])
    _require(receipt is not None and receipt['world_sha256']==digest(world),'VERIFIED_UPDATE_RECEIPT_REQUIRED')
    parent=store.get_world(receipt['parent_world_id']);verify_world_hash(parent)
    _require(digest(parent)==receipt['parent_sha256'],'UPDATE_PARENT_CHANGED')
    _require(world['binding']['reference_world_id']==parent['world_id']
             and world['world_revision']==parent['world_revision']+1,'UPDATE_PARENT_REVISION')
    if parent['state'].get('geometry_update_version'):validate_geometry_update(store,parent,False,full_audit=full_audit)
    elif requires_binding_check(store,parent):validate_persistent_world(store,parent,False)
    obs=store.get(receipt['observation_id'])
    _require(digest(obs)==receipt['observation_sha256'],'UPDATE_OBSERVATION_CHANGED')
    _require(world['state']['robot_state']==obs['state']
             and world['binding']['execution_epoch']==obs['execution_epoch']
             and world['state']['observation_id']==obs['observation_id'],'UPDATE_CURRENT_BINDING')
    for camera in ('assembly','fixed','wrist'):
        store.image(obs['observation_id'],camera);store.depth(obs['observation_id'],camera)
    _require(world['read_versions']==receipt['read_versions'],'UPDATE_READ_VERSIONS')
    if require_current:
        _require(store.current_world_id==world['world_id'] and store.revision==world['world_revision']
                 and store.read_versions==world['read_versions'],'STALE_GEOMETRY_UPDATE')
    return True


def validate_geometry_update(store,world,require_current=True,*,full_audit=False):
    """Fast immutable proof path; full_audit rechecks original files/ancestor content."""
    cache=store.verification_cache
    if require_current:
        _require(store.current_world_id==world['world_id'] and store.revision==world['world_revision']
                 and store.read_versions==world['read_versions'], 'STALE_GEOMETRY_UPDATE')
    if full_audit:
        with cache.audit():return _validate_geometry_update(store,world,require_current,True)
    if cache.hit(world):return True
    with cache.transaction(world['state']['observation_id']):
        result=_validate_geometry_update(store,world,require_current)
        cache.remember(world)
        return result
