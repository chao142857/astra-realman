"""Loopback-only HTTP acceptance. Never calls the live runner."""
import json
import shutil
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra_gui import make_server
from real_chunk_gui import OfflineChunkConsole,fixture

class HTTPMigration(unittest.TestCase):
    def setUp(self):
        self.console=OfflineChunkConsole();self.server=make_server(self.console,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2);self.console.close()
        shutil.rmtree(self.console.session)
        if self.console.current_run:shutil.rmtree(self.console.current_run)
    def post(self, path, body, authenticated=True):
        headers={'Content-Type':'application/json'}
        if authenticated:headers['X-Astra-Token']=self.console.token
        return urllib.request.urlopen(urllib.request.Request(self.console.url+path,data=json.dumps(body).encode(),headers=headers),timeout=5)
    def test_unauthenticated_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.post('/api/start',{},False)
        self.assertEqual(ctx.exception.code,403);self.assertIsNone(self.console.current_run)
    def test_fake_start_export_and_no_real_override(self):
        with patch('astra_gui.subprocess.Popen',side_effect=AssertionError('live process forbidden')):
            with self.post('/api/start',{'mode':'execute','raw_proposal':json.dumps(fixture())}) as response:
                run=json.load(response)['run']
        with urllib.request.urlopen(self.console.url+'/api/export?run='+run) as response:data=json.load(response)
        self.assertEqual(data['summary']['model_calls'],0)
        self.assertEqual(len(data['steps'][0]['operations']),4)
        self.assertEqual(data['summary']['hardware_commands_sent'],0)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/annotate',{'run':run,'result':'success'})

if __name__=='__main__':unittest.main()
