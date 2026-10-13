#!/usr/bin/env python3
"""Archive a complete fake Pilot02 batch. No production endpoints or subprocesses."""
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pilot02_dispatcher as d
import pilot02_runtime as r
from pilot02_mock import mock_bridge


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    root=args.output.resolve()
    with patch('subprocess.Popen',side_effect=AssertionError('ZERO_GENERATION_NO_SUBPROCESS')):
        state=d.prepare(root)
        state.update(mode='OFFLINE_FIXTURE',status='READY');d.save(root/'ledger.json',state)
        with tempfile.TemporaryDirectory() as temp, mock_bridge(Path(temp)) as mock:
            def control(job,key='witness'):
                return r.read((r.MODULE/job['input_directory']).parent.parent/'private/design_and_controls.json')[key]
            def runner(job,folder):
                mock['raw']=json.dumps(control(job))
                return d.perform(job,folder,mock['config'],offline=True)
            with d.lock():d.advance(root,state,runner,20)
            assert state['status']=='COMPLETE' and mock['decide_calls']==20
            checks=[]
            def case(name,job,raw,mode='success',timeout=180,valid=False,score=None):
                mock.update(raw=raw,mode=mode)
                context,images,*_=r.job_input(job);folder=root/'faults'/name
                before=mock['decide_calls']
                adapter=r.Pilot02MacBridgeAdapter(mock['config'],job,offline_test=True)
                response=adapter.infer(context,images,folder,timeout_s=timeout)
                result=r.record_and_rescore(folder,job)
                assert result['status']==('VALID' if valid else 'NOT_SCORED'),(name,result)
                assert result['score']==score and response['model_calls']==0
                assert mock['decide_calls']==before+1
                checks.append({'name':name,'status':'PASS','assessment':result,'artifact':str(folder.relative_to(root))})
            job=state['jobs'][0];raw=json.dumps(control(job))
            for mode in ('invalid_json','empty','no_completed','duplicate_completed','failed_event','return_error','transport_error','parameter_drift','code_mode_drift'):
                case(mode,job,raw,mode)
            mock['config'].token_file.write_text('WRONG_OFFLINE_CREDENTIAL_ONLY')
            case('http403',job,raw)
            mock['config'].token_file.write_text('OFFLINE_FIXTURE_NOT_A_REAL_CREDENTIAL')
            mock['busy'].acquire()
            try:case('http409',job,raw)
            finally:mock['busy'].release()
            case('timeout_cancel_unknown',job,raw,'timeout',timeout=.08)
            for i,job in enumerate(state['jobs']):
                for name,prediction in control(job,'negative_controls').items():
                    case(f'negative-{i:02d}-{name}',job,json.dumps(prediction),valid=True,score=0)
                for n,prediction in enumerate(control(job,'alternate_witnesses')):
                    case(f'alternate-{i:02d}-{n}',job,json.dumps(prediction),valid=True,score=1)
            # A/C public payloads must differ only in geometry. Fixture answers are
            # held in the fake server, never copied into the request context.
            for a,c in zip(mock['payloads'][:20:2],mock['payloads'][1:20:2]):
                aa=dict(a['context'],geometry=None);cc=dict(c['context'],geometry=None)
                assert aa==cc and a['images']==c['images']
            summary={'status':'PASS','source':'OFFLINE_FIXTURE_NOT_ASTRA','real_generation_requests':0,
                     'production_bridge_contacted':False,'complete_frozen_samples':20,'pairs':10,
                     'all_independent_rescores_equal':True,'frozen_files_verified':len(r.read(r.SEAL)['entries']),
                     'fault_and_control_checks':checks,'fake_http_dispatches':mock['decide_calls'],
                     'cancel_requests':mock['cancel_calls'],'budget_note':'OFFLINE_FIXTURE reservations are simulated; cannot authorize or resume as REAL.'}
            d.save(root/'acceptance.json',summary)
            print(json.dumps({k:v for k,v in summary.items() if k!='fault_and_control_checks'},indent=2))

if __name__=='__main__':main()
