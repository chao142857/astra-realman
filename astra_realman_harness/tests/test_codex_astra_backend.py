import copy,json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT
from codex_astra_backend import CodexAstraBackend
from decision_backends import BackendFailure
from left_terminal_fourview import parse,SCHEMA_PATH

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='official-backend-test-')
        self.run=Path(self.temp.name)
        self.image=self.run/'image.png';self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.context={'task':'unchanged task','images_in_attachment_order':[{'image_path':str(self.image),'role':'test'}],'previous':{'x':1}}
        self.action={'action_type':'cartesian_delta','arm':'left','frame':'realman:left:work:World',
                     'tool_frame':'realman:left:tool:Arm_Tip','translation_m':[.012,0,.08],
                     'rotation_rpy_rad':[0,0,0],'gripper_opening':.25,'done':False}
        self.raw=json.dumps(self.action)
        self.response={'return_code':0,'raw':self.raw,'events':'\n'.join(json.dumps(x) for x in [
            {'type':'turn.started'},{'type':'item.completed','item':{'type':'agent_message','text':self.raw}},
            {'type':'turn.completed'}]),'mac_home':'/Users/test','command':['codex','exec'],'stderr':''}
        self.stop=threading.Event();self.payload=None
        self.backend=CodexAstraBackend({'bridge_url':'http://127.0.0.1:18766','timeout_s':2},self.run,
            'gpt-6-astra',self.stop,lambda *a:None,SCHEMA_PATH,parse)
    def tearDown(self):self.temp.cleanup()
    def transport(self,req,timeout):
        self.payload=json.loads(req.data)
        data=json.dumps(self.response).encode()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return data
        return Response()
    def call(self):
        original=Path.read_text
        def fixture_token(path,*args,**kwargs):
            if path==ROOT/'config/codex_astra_bridge.token':return 'OFFLINE_FIXTURE_NOT_A_CREDENTIAL'
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',fixture_token),patch('codex_astra_backend.urllib.request.urlopen',self.transport):
            return self.backend.decide(self.context,self.context['images_in_attachment_order'])
    def test_exact_context_action_and_raw(self):
        before=copy.deepcopy(self.context);self.assertEqual(self.call(),self.action)
        self.assertEqual(self.context,before);self.assertEqual(self.payload['context'],before)
        self.assertEqual(self.backend.raw,self.raw);self.assertEqual((self.run/'astra_raw.txt').read_text(),self.raw)
    def test_backend_failure_not_ik(self):
        self.response.update(return_code=1,error='HTTP failure')
        with self.assertRaises(BackendFailure) as got:self.call()
        self.assertEqual(got.exception.code,'CODEX_ASTRA_CALL_FAILED')
    def test_invalid_action(self):
        self.raw='{}';self.response['raw']=self.raw
        self.response['events']=self.response['events'].replace(json.dumps(json.dumps(self.action)),json.dumps(self.raw))
        with self.assertRaises(BackendFailure):self.call()
    def test_tool_event_rejected(self):
        self.response['events']+='\n'+json.dumps({'type':'item.completed','item':{'type':'command_execution'}})
        with self.assertRaises(BackendFailure):self.call()
    def test_stop_prevents_request(self):
        self.stop.set()
        with self.assertRaises(BackendFailure):self.call()
        self.assertIsNone(self.payload)
    def test_no_provider_fallback(self):
        self.backend.config['bridge_url']='https://xmapi.site/v1'
        with self.assertRaises(BackendFailure):self.call()
        self.assertIsNone(self.payload)

if __name__=='__main__':unittest.main()
