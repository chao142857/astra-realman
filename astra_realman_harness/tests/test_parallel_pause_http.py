import sys, threading, unittest, json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra_gui import make_server
from parallel_safety_pause import require_automation_ready
class PauseHTTP(unittest.TestCase):
 def test_pause_returns_json_not_disconnected_socket(self):
  c=SimpleNamespace(token='offline-test',start=lambda _:require_automation_ready())
  server=make_server(c,0);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   req=Request(c.url+'/api/start',data=b'{}',headers={'X-Astra-Token':c.token,'Content-Type':'application/json'})
   with patch('parallel_safety_pause.AUTOMATION_PAUSED',True):
    with self.assertRaises(HTTPError) as e:urlopen(req,timeout=3)
   self.assertEqual(e.exception.code,409)
   body=json.load(e.exception);self.assertFalse(body['request_accepted'])
   self.assertIn('PARALLEL_AUTOMATION_PAUSED',body['error'])
  finally:server.shutdown();server.server_close();thread.join()
