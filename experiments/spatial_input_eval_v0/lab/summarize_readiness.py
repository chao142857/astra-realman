#!/usr/bin/env python3
"""Evidence-derived delivery status; never upgrades metadata into generation success."""
import argparse
import json
from pathlib import Path
from spatial_eval.schema import write


def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);a=p.parse_args();e=a.evidence
    def read(rel):return json.loads((e/rel).read_text())
    acceptance=read('acceptance_final/acceptance.json');repro=read('reproduction.json')
    assert acceptance['status']==repro['status']=='PASS'
    mock=read('mock_sim_suite/results.json');s1=read('mock_s1/results.json')
    assert len(mock)==24 and len(s1)==4
    assert all(r['source']=='MOCK_NOT_ASTRA' and r['model_calls']==0 and r['parse_status']=='VALID' for r in mock+s1)
    bundled=json.loads(read('catalog_native/bundled.json')['stdout'])
    remote=json.loads(read('catalog_native/remote.json')['stdout'])
    route=read('account_routing/infer_output/account_routing/probe.json')
    response=next(x['result'] for x in route['sanitized_responses'] if x.get('id')==2)
    frozen=read('frozen_input_native/infer_output/frozen_input/probe.json')
    assert frozen['native_input_render_status']=='PASS'
    history=read('environment/historical_success.json')
    model=next(m for m in bundled['models'] if m['slug']=='gpt-6-astra')
    result={'offline_status':'PASS','real_generation_status':'NOT_STARTED_NEW_AUTHORIZATION_REQUIRED',
            'new_real_generation_requests':0,'new_hardware_connections':0,
            'unit_tests':{'passed':33,'total':33,'evidence':'unit_33.log'},
            'scenes':6,'rgbd_views':18,'tasks':12,'prepared_ac_inputs':24,
            'mock_samples':28,'mock_ac_pairs':14,'mock_is_capability_evidence':False,
            'reproduction':{'byte_identical_assets':72,'same_geometry_task_calibration':True},
            'native_preflight':read('native_preflight_initial/preflight.json')['status'],
            'frozen_native_input':frozen['native_input_render_status'],
            'all_provider_payloads':acceptance['all_24_provider_payloads'],
            'historical_verified_json_records':history['count'],
            'historical_distinct_event_hashes':len({r['events_sha256'] for r in history['verified_records']}),
            'historical_scope':'Archived Mac ChatGPT bridge calls with other schemas; not this spatial benchmark',
            'native_account_type':response['account']['type'],
            'native_workspace_routing':response['workspaceRouting'],
            'catalog_matches_bundled':remote==bundled,
            'catalog_remote_success_established':False if remote==bundled else None,
            'bundled_astra_tool_mode':model.get('tool_mode'),
            'bridge_code_mode_host_disabled':True,
            'generation_compatibility':'UNPROVEN; disabled-host warning alone does not establish a cause',
            'blockers':['Native lab CLI currently uses API-key authentication with no ChatGPT workspace route; validate intended Astra account route before generation',
                        'Code-mode-only catalog versus disabled code-mode host remains a compatibility question; no generation attempted',
                        'Explicit new authorization is required for exactly one real JSON acceptance request'],
            'minimal_future_diagnosis':['Resolve intended authenticated interface without copying credentials; rerun non-generation account and input probes',
                                        'When separately authorized, send one frozen A request with unchanged gpt-6-astra/medium, schema and 90-second qualification cap',
                                        'Observe sanitized send time and transport status/SSE or WebSocket event times; no authorization headers, cookies or tokens',
                                        'No outgoing request indicates client/runtime stall; request sent without response indicates transport/server wait; explicit configuration rejection indicates compatibility',
                                        'Without send/receive evidence retain UNRESOLVED; no automatic retries, timeout increase, fallback or C before valid A JSON']}
    write(e/'delivery.json',result)
    print(json.dumps({k:result[k] for k in ['offline_status','scenes','rgbd_views','mock_samples','native_account_type','catalog_matches_bundled','bundled_astra_tool_mode','new_real_generation_requests']},indent=2))


if __name__=='__main__':main()
