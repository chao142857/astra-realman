"""Build reviewable diagnostic plans ONLY. There is deliberately no execution API."""
import argparse
import json
from pathlib import Path
from local_protocol_probe import ROOT, save


def plan():
    record=json.loads((ROOT/'evidence/routing_repair/real_A_qualification/sample-0000/infer_output/worker_record.json').read_text())
    old=record['command'];flags=[]
    i=0
    while i<len(old):
        if old[i] in ('--disable','-c'):
            key,value=old[i:i+2]
            if key=='--disable' or not value.startswith(('model_provider=','log_dir=','sqlite_home=')):
                flags.extend([key,value])
            i+=2
        else:i+=1
    argv=['/runtime/bin/codex','exec','--ignore-user-config','--ignore-rules','--sandbox','read-only',
          '--ephemeral','--skip-git-repo-check','--cd','/output/input_only','--color','never',
          '--json','--model','gpt-6-astra','--output-last-message','/output/last_message.txt',*flags,
          '-c','log_dir="/output/runtime"','-c','sqlite_home="/output/runtime"']
    provider='model_providers.astra_diag_openai_http_once'
    single=[*argv,'-c','model_provider="astra_diag_openai_http_once"',
            '-c',provider+'.name="OpenAI"','-c',provider+'.wire_api="responses"',
            '-c',provider+'.requires_openai_auth=true','-c',provider+'.supports_websockets=false',
            '-c',provider+'.request_max_retries=0','-c',provider+'.stream_max_retries=0',
            '-c','features.unbounded_connection_retries=false','-']
    return {'status':'PLAN_ONLY_NOT_AUTHORIZED','authorized_real_generation_budget':0,
        'prompt':'Reply with exactly ASTRA_TEXT_OK. Do not use tools.',
        'model':'gpt-6-astra','reasoning_effort':'medium','images':[],'output_schema':None,
        'wall_cap_s':90,'application_retries':0,'real_requests_executed':0,
        'baseline_native_ws_argv':[*argv,'-c','model_provider="openai"','-'],
        'baseline_budget_status':'DO_NOT_RUN under single-request no-retry constraint: built-in request/stream defaults and WS->HTTP retry may exceed one generation.',
        'proposed_single_http_argv':single,
        'transport_delta':'Same OpenAI service/auth/routing/model/effort, custom config ID only to force HTTP/SSE and zero retries; NOT an alternate vendor or model. Needs explicit authorization of this diagnostic delta.',
        'single_http_limit':'No application/transport automatic retries verified with local 503 and truncated SSE fixtures. Tool follow-up/auth recovery must also be gated in a future launcher; this file is not runnable.',
        'required_before_execution':['New explicit authorization for one native text request and diagnostic transport delta',
          'Host execution net namespace matching successful original bwrap account-read; no restricted outer namespace rerun',
          'Independent bwrap with original network/filesystem isolation and read-only existing auth at original path',
          'No GT, scoring code, historical results, scene setup, robot controllers, home-directory-wide mounts',
          'Phase-only OTLP allowlist collector; no raw telemetry/resource attributes/auth headers persisted',
          'Stop on tool request, error or 90 s deadline; prevent tool-driven follow-up and unauthorized auth recovery/replay; verify that guard locally before any real request'],
        'acceptance':['normal turn.completed','nonempty genuine assistant output','raw request/response/stdout/stderr/timing/available usage saved',
                      'for plain text stage: no geometry scoring and no JSON schema required'],
        'after_text_success':'Separate new authorization for tiny strict JSON request; then separate frozen S1 A; only after valid A seek separate C authorization. No automatic progression.',
        'host_enabled_diagnostic_design':{'status':'NOT_NEEDED_FOR_TEXT_BASED_ON_SOURCE_AND_LOCAL_FIXTURE',
          'production_bridge_change':False,'feature_delta':{'features.code_mode_host':True},
          'readonly_binary_layout':['/runtime/bin/codex','/runtime/bin/codex-code-mode-host'],
          'host_package_version':'0.162.1','protocol':'V1 handshake already PASS without executing a cell',
          'constraints':'Keep all original other flags, bwrap and input-only mounts. No catalog modification or tool privilege expansion.',
          'tool_permission_gate':'The catalog-driven Responses Lite request still advertises exec/wait and collaboration/clock tools despite disabled feature flags. Do not enable host in a hosted turn until strict diagnostic tool denial is separately designed and verified. Current host test negotiated empty capabilities and executed zero cells.'}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('REFUSE_OVERWRITE')
    save(args.output,plan());print('PLAN_ONLY real_generation_budget=0 execution_api=absent')
