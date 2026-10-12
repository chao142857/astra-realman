"""Read-only source/version/historical-success audit; never opens auth files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from local_protocol_probe import NATIVE, HOST, ROOT, save

SOURCE = Path('/tmp/astra-codex-01621-source')
PIN = '092d3acd6bec3e3a14bdc7e7a2810ab628ab759d'
EXCERPTS = {
 'core/src/tools/mod.rs':[(75,100)],
 'core/src/session/turn_context.rs':[(1405,1448)],
 'core/src/tools/code_mode/mod.rs':[(90,170)],
 'core/src/tools/spec_plan.rs':[(716,735),(861,890),(965,1020)],
 'core/src/thread_manager.rs':[(568,579)],
 'code-mode/src/remote_session.rs':[(1,112)],
 'install-context/src/lib.rs':[(176,210)],
 'code-mode-protocol/src/host/codec.rs':[(1,145)],
 'code-mode-protocol/src/host/message.rs':[(125,245)],
 'model-provider-info/src/lib.rs':[(64,76),(490,526),(540,565),(699,737)],
 'core/src/client.rs':[(1,36),(870,950),(1030,1085),(1880,1950),(2176,2230),(2237,2305)],
 'core/src/responses_retry.rs':[(55,174)],
 'core/src/session/startup_prewarm.rs':[(410,465)],
 'codex-api/src/endpoint/responses.rs':[(80,180)],
 'codex-api/src/endpoint/session.rs':[(45,165)],
 'http-client/src/transport.rs':[(148,175),(215,268)],
 'codex-api/src/endpoint/responses_websocket/connector.rs':[(1,60)],
 'codex-api/src/endpoint/responses_websocket.rs':[(245,300),(725,760)],
 'codex-api/src/sse/responses.rs':[(345,465),(528,588)],
 'core/src/session/turn.rs':[(1620,1640),(2650,2685),(2946,3009)],
 'exec/src/event_processor_with_jsonl_output.rs':[(407,455),(475,545),(590,600)],
 'exec/src/lib.rs':[(254,261),(338,342),(684,693)],
 'otel/src/events/session_telemetry.rs':[(785,816),(842,877),(893,915),(946,1004),(1057,1075)],
 'config/src/types.rs':[(597,649)],
}


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def collect(output):
    output.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
    if commit!=PIN: raise ValueError('SOURCE_PIN_MISMATCH')
    excerpts=output/'source'; excerpts.mkdir()
    shutil.copy2(SOURCE/'LICENSE',excerpts/'LICENSE')
    records=[]
    for name,ranges in EXCERPTS.items():
        p=SOURCE/'codex-rs'/name; lines=p.read_text().splitlines()
        text='\n'.join(('%s:%d: %s'%(name,i,lines[i-1])).rstrip() for start,end in ranges
                       for i in range(start,min(end,len(lines))+1))+'\n'
        dest=excerpts/(name.replace('/','__')+'.txt'); dest.write_text(text)
        records.append({'path':'codex-rs/'+name,'full_source_sha256':digest(p),
                        'line_ranges':ranges,'excerpt':str(dest.relative_to(output)),
                        'official_url':'https://github.com/openai/codex/blob/'+PIN+'/codex-rs/'+name})
    save(output/'source_pin.json',{'repository':'https://github.com/openai/codex.git',
       'tag':'rust-v0.162.1','commit':commit,'files':records})
    package=HOST.parent.parent/'codex-package.json'
    save(output/'installed.json',{'cli_version':subprocess.check_output([str(NATIVE),'--version'],text=True).strip(),
       'native_binary':str(NATIVE),'native_sha256':digest(NATIVE),'host_binary':str(HOST),
       'host_sha256':digest(HOST),'host_package_manifest':json.loads(package.read_text()),
       'host_version_method':'release manifest + binary hash + successful V1 handshake; executable has no --version',
       'original_bridge_mounts_host':False,'host_discovery':'InstallContext bundled resource then sibling executable; PATH alone is insufficient',
       'real_model_calls':0})
    oldroot=Path('/home/alex/astra-realman_ws/semantic-s1-provider-fix-20261009')
    oldmanifest=json.loads((oldroot/'FINAL_FIX_MANIFEST.json').read_text())
    native=oldroot/'runtime_cli/libexec/codex'; shim=oldroot/'runtime_cli/bin/codex'
    nativehash=digest(native); shimhash=digest(shim)
    if nativehash!=oldmanifest['native_binary_sha256'] or shimhash!=oldmanifest['launcher_sha256']:
        raise ValueError('HISTORICAL_LAUNCHER_SEAL_MISMATCH')
    shutil.copy2(shim,output/'historical_launcher.py.txt')
    save(output/'historical_version_seal.json',{'manifest':oldmanifest,'manifest_sha256':digest(oldroot/'FINAL_FIX_MANIFEST.json'),
        'current_native_sha256':nativehash,'current_shim_sha256':shimhash,
        'version_read_only':subprocess.check_output([str(native),'--version'],text=True).strip(),
        'seal_matches':True})
    by_thread={}; total=0
    for root in ('ab-cached-scenes-20261011','run-full-pnp-approach-20261010'):
        for path in (Path('/home/alex/astra-realman_ws')/root).rglob('worker_record.json'):
            record=json.loads(path.read_text())
            if not record.get('raw') or record.get('return_code')!=0 or 'turn.completed' not in record.get('events',''):
                continue
            total+=1
            events=[json.loads(s) for s in record['events'].splitlines() if s.startswith('{')]
            thread=next(e['thread_id'] for e in events if e['type']=='thread.started')
            if thread in by_thread:
                by_thread[thread]['copies'].append(str(path)); continue
            effective=path.parent/'effective_cli_argv.json'
            if not effective.exists(): raise ValueError('HISTORICAL_EFFECTIVE_ARGV_MISSING')
            argv=json.loads(effective.read_text())
            usage=next(e.get('usage') for e in events if e['type']=='turn.completed')
            entry={'thread_id':thread,'copies':[str(path)],'worker_record_sha256':digest(path),
                   'effective_argv_sha256':digest(effective),'effective_argv':argv,
                   'warning_fail_closed':any('fail closed' in json.dumps(e) for e in events),
                   'raw_bytes':len(record['raw'].encode()),'usage':usage,'latency_s':record.get('latency_s'),
                   'classification':'HISTORICAL_REAL_SUCCESS_NOT_CURRENT_S1_EVAL',
                   'http_only':any('supports_websockets=false' in x for x in argv),
                   'request_retries_zero':any('request_max_retries=0' in x for x in argv),
                   'stream_retries_zero':any('stream_max_retries=0' in x for x in argv)}
            by_thread[thread]=entry
            # Preserve two complete raw success records; remaining copies indexed and hashed.
            if len(by_thread)<=2:
                dest=output/('historical_success_%02d'%len(by_thread));dest.mkdir()
                shutil.copy2(path,dest/'worker_record.json')
                shutil.copy2(effective,dest/'effective_cli_argv.json')
                (dest/'events.jsonl').write_text(record['events'])
                (dest/'raw.txt').write_text(record['raw'])
                run=Path(record.get('local_log','')).name
                envpath=path.parent/'bridge'/run/'environment.json'
                if envpath.exists():
                    env=json.loads(envpath.read_text());save(dest/'environment_keys.json',sorted(env))
    save(output/'historical_comparison.json',{'successful_record_copies':total,
         'distinct_successful_threads':len(by_thread),'calls':list(by_thread.values()),
         'limit':'Versions sealed for shim/native. Effective argv ties calls to that entrypoint. No inference that 0.162.1 hosted transport is working.',
         'new_real_model_calls':0})
    print('archived source files=%d historical distinct=%d copies=%d'%(len(records),len(by_thread),total))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    collect(parser.parse_args().output.resolve())
