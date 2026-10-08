"""No real processes/models/physics: budget and stop boundary tests for the ledger."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_sim_ms_pilot as batch


class BatchTests(unittest.TestCase):
    def test_usage_same_fields_only_preserves_subcounts_and_missing(self):
        usages=[{'input_tokens':10,'cached_input_tokens':4,'output_tokens':6,'reasoning_output_tokens':2,
                 'details':{'other':3}}, {'input_tokens':20,'cached_input_tokens':5,'output_tokens':7,
                 'reasoning_output_tokens':1,'details':{'other':4}},None]
        result=batch.usage_totals(usages)
        self.assertEqual(result['sum_of_observed_same_fields'],{'input_tokens':30,'cached_input_tokens':9,
                         'output_tokens':13,'reasoning_output_tokens':3,'details':{'other':7}})
        self.assertEqual(result['raw_per_request'],usages)
        self.assertFalse(result['complete']);self.assertEqual(result['missing_usage_requests'],1)

    def test_classification_stop_task_fail_and_exception(self):
        requests=[{'metadata':{'status':'COMPLETE'},'parsed':{'action':'stop'}}]
        result={'model_calls':1,'status':'FAIL','placement':{'model_attempts':1,'status':'FAIL','error':'RuntimeError:POLICY_STOP'}}
        self.assertEqual(batch.classify(result,requests,[],1),('STOP',False))
        result['placement']['error']=None
        requests[0]['parsed']['action']='continue'
        events=[{'kind':'INDEPENDENT_EVALUATION','data':{'status':'FAIL'}}]
        self.assertEqual(batch.classify(result,requests,events,1),('TASK_FAIL',False))
        result['placement']['error']='RuntimeError:EXECUTION_FAILED_NO_RETRY'
        self.assertTrue(batch.classify(result,requests,[],1)[1])
        requests[0]['metadata']['status']='FAILED'
        self.assertEqual(batch.classify(result,requests,[],1),('ABORT_INTERFACE',True))
        self.assertEqual(batch.classify({'model_calls':0},[],[],1),('ABORT_INITIALIZATION',True))
        requests[0]['metadata']['status']='COMPLETE';requests[0]['parsed']['action']='invalid'
        self.assertEqual(batch.classify(result,requests,[],1),('ABORT_PROTOCOL',True))

    def driver(self,summary):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'batch';commands=[]
            class Process:
                pid=12345
                def __init__(self,cmd,**kw):commands.append(cmd)
                def wait(self,**kw):return 0
                def poll(self):return 0
            argv=['batch','--assets',str(Path(tmp)/'assets'),'--output',str(root),
                  '--codex-executable','/bin/false','--authorize-model','--max-model-requests','10']
            with patch.object(sys,'argv',argv),patch.object(batch.subprocess,'Popen',Process), \
                 patch.object(batch,'summarize',side_effect=summary),patch.object(batch.signal,'signal'), \
                 contextlib.redirect_stdout(io.StringIO()):code=batch.main()
            return code,commands,json.loads((root/'ledger.json').read_text())

    def test_exact_order_caps_and_legal_stop_does_not_get_replaced(self):
        def summary(path,code):
            stop=path.name.startswith('01-')
            return {'status':'STOP' if stop else 'PASS','abort_batch':False,'actual_requests':1 if stop or path.name.endswith('-S') else 4,
                    'versions':{'fixture':'same'},'stop_reason':'RuntimeError:POLICY_STOP' if stop else None}
        code,commands,ledger=self.driver(summary)
        self.assertEqual(code,0);self.assertEqual(len(commands),4)
        self.assertEqual([(c[c.index('--seed')+1],c[c.index('--condition')+1],c[c.index('--max-model-requests')+1]) for c in commands],
                         [('2','M','4'),('2','S','1'),('3','S','1'),('3','M','4')])
        self.assertTrue(all(c[c.index('--budget-s')+1]=='120' and '--video' not in c for c in commands))
        self.assertEqual(ledger['allocated_caps'],10)
        self.assertEqual(ledger['episodes'][0]['status'],'STOP')
        self.assertEqual(ledger['actual_requests_observed'],7)

    def test_interface_failure_stops_later_rounds_and_consumes_attempt(self):
        code,commands,ledger=self.driver(lambda *a:{'status':'ABORT_INTERFACE','abort_batch':True,
            'actual_requests':1,'stop_reason':'RuntimeError:CLI_REQUEST_FAILED'})
        self.assertEqual(code,1);self.assertEqual(len(commands),1)
        self.assertEqual(ledger['actual_requests_observed'],1)
        self.assertEqual([r['status'] for r in ledger['episodes'][1:]],['NOT_RUN']*3)
        self.assertEqual([r['actual_requests'] for r in ledger['episodes'][1:]],[0]*3)


if __name__=='__main__':unittest.main()
