"""Prepare exact production proposal schemas/input; NEVER dispatch or create a claim."""
import argparse,ast,hashlib,json,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from platform_v1.research.public_store import PublicStore
from platform_v1.research.semantic_binding import import_grounding_archive,restore_persistent_world
from platform_v1.research.broker import Broker
from platform_v1.research.action_proposal import proposal_request,VERSION
from scripts.structured_outputs import check_provider

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n')
def prepare(ws,out):
    t=time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    sem=ws/'semantic-grounding-authorized-01-20261010';old=ws/'candidate-v2-a-h4-authorized-01-20261010'
    cfg=read(ROOT/'config/research/persistent_semantic_s1_v1.json');o=read(sem/'OBSERVATION.json')
    base=read(ws/'geometry-first-v2-20261010/results/geometry/WORLD.json')
    world=read(ws/'persistent-semantic-binding-20261010/result/WORLD.json')
    store=PublicStore(sem/'public_rgb_only',o['episode_id']);store.observe(o,o['execution_epoch'])
    store.worlds[base['world_id']]=base;store.current_world_id=base['world_id'];store.revision=1;store.read_versions=base['read_versions']
    import_grounding_archive(store,sem,cfg['archive_manifest_sha256'],base['world_id'],cfg['evidence_id'])
    restore_persistent_world(store,world,world['world_id'],cfg['task'])
    broker=Broker(out/'broker',store,SimpleNamespace(fixture=False),deadline=time.monotonic()+90,
        epoch=lambda:o['execution_epoch'],allowance=lambda:0,baseline_busy=lambda:False,emit=lambda *x:None)
    request=proposal_request(world,o);result=broker.prepare(request);row=broker.rows[result['request_id']]
    assert broker.calls==broker.infer_calls==0 and broker.job is None and broker.action_ready is None
    save(out/'REQUEST.json',request);save(out/'WORLD_QUERY.json',store.query_world(world['world_id']))
    save(out/'HOST_CONTEXT.json',row['proposal_host'])
    folder=out/'broker'/result['request_id']
    for source,dest in [('schema.json','PROVIDER_SCHEMA.json'),('authoritative_schema.json','AUTHORITATIVE_SCHEMA.json'),('schema_audit.json','SCHEMA_AUDIT.json')]:
        (out/dest).write_bytes((folder/source).read_bytes())
    check_provider(row['provider_schema'])
    wire=read(folder/'input_only/wire.json')
    assert len(wire['attachments'])==3
    old_auth=read(old/'AUTHORIZATION.json')
    launcher=Path(old_auth['launcher']);binary=launcher.parent.parent/'libexec/codex'
    assert sha(launcher)==old_auth['launcher_sha256'] and sha(binary)==old_auth['native_binary_sha256']
    settings=next(ast.literal_eval(n.value) for n in ast.parse(launcher.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='settings' for t in n.targets))
    assert settings['model_providers.s1_openai_no_retry.request_max_retries']=='0'
    assert settings['model_providers.s1_openai_no_retry.stream_max_retries']=='0'
    assert settings['features.unbounded_connection_retries']=='false'
    from scripts.codex_astra_mac_bridge import command
    dummy=Path('/output/bridge/ATTEMPT')
    argv=command(dummy,[dummy/'input_only'/('image-%d.png'%i) for i in range(3)],str(launcher))
    args=[x.replace('model_provider="openai"','model_provider="s1_openai_no_retry"') for x in argv[1:]]
    effective=[str(binary),args[0],*[x for k,v in settings.items() for x in ('-c',k+'='+v)],*args[1:]]
    save(out/'EXPECTED_EFFECTIVE_ARGV.json',effective)
    assert 'model_reasoning_effort="medium"' in effective and effective[effective.index('--model')+1]=='gpt-6-astra'
    for a in row['attachments']:
        orig=next(x for x in old_auth['three_RGB'] if x['camera']==a['camera'])
        assert a['source_sha256']==a['sha256']==orig['sha256']
    for forbidden in ('RGB_REFERENCE','SCORING_TRUTH','s1_red_distractor','s1_blue_distractor'):
        assert forbidden not in json.dumps(wire)
    assert 'depth' not in wire['observations'][o['observation_id']]
    paths=sorted(p for p in ROOT.rglob('*.py') if '__pycache__' not in str(p))+sorted((ROOT/'config').rglob('*.json'))
    save(out/'SOURCE_SHA256.json',{str(p.relative_to(ROOT)):sha(p) for p in paths})
    template={'version':'astra.action_proposal_authorization.v1','scope':'ACTION_PROPOSAL_V1_H4_SHADOW_ONLY',
        'granted':False,'authorization_id':None,'request_claim':None,'requires_new_explicit_authorization':True,
        'source_commit':'See GIT_DELIVERY.json; recheck clean tree and hashes before any future request',
        'output_contract':VERSION,'model':old_auth['model'],'effort':old_auth['effort'],
        'launcher':str(launcher),'launcher_sha256':sha(launcher),'native_binary_sha256':sha(binary),
        'production_provider_and_auth':'UNCHANGED; credentials neither read nor copied by this preparation',
        'max_Broker_submissions':1,'timeout_s':90,'application_retries':0,'request_max_retries':0,'stream_max_retries':0,
        'unbounded_connection_retries':False,'fallbacks':0,'server_internal_retries':'UNKNOWN',
        'world_id':world['world_id'],'world_revision':world['world_revision'],'execution_epoch':o['execution_epoch'],
        'read_versions':world['read_versions'],'semantic_evidence_id':cfg['evidence_id'],
        'task':cfg['task'],'target':'object_004','H':4,'m':1,'K':0,'grants_execution':False,
        'task_usable':'unknown','request_sha256':sha(out/'REQUEST.json'),
        'provider_schema_sha256':sha(out/'PROVIDER_SCHEMA.json'),'authoritative_schema_sha256':sha(out/'AUTHORITATIVE_SCHEMA.json'),
        'wire_sha256':sha(folder/'input_only/wire.json'),'source_manifest_sha256':sha(out/'SOURCE_SHA256.json'),
        'RGB':row['attachments'],'E':0,'new_SAPIEN':0,'hardware':0,'training':0,
        'preparation_id_is_not_attempt':'prepare-001 must never be reused as an authorized attempt'}
    save(out/'AUTHORIZATION_TEMPLATE.json',template)
    save(out/'PREPARATION_RESULT.json',{'status':'PREPARED_NOT_DISPATCHED','production_input':True,'real_new_contract_acceptance':'NOT_TESTED',
        'prepare_wall_s':time.perf_counter()-t,'Broker_submissions':broker.calls,'infer_starts':broker.infer_calls,
        'usage':None,'wire_bytes':(folder/'input_only/wire.json').stat().st_size,
        'provider_schema_bytes':(out/'PROVIDER_SCHEMA.json').stat().st_size,'task_usable_unchanged':world['state']['geometry_quality']['task_usable']})
    print(json.dumps(template | {'RGB':'see saved manifest'},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();prepare(a.archive_root,a.out)
