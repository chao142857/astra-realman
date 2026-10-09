"""Offline symlink/old-Node regression. All launchers here are local test doubles."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import codex_astra_mac_bridge as bridge
from scripts import run_sim_placement as runner
from bimanual_demo.evidence import PNG


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.bin=self.root/'nvm/bin';self.script_dir=self.root/'package/bin'
        self.system=self.root/'system-bin'
        for directory in (self.bin,self.script_dir,self.system):directory.mkdir(parents=True)
        self.launcher=self.bin/'codex';self.script=self.script_dir/'codex.js'
        self.launcher.symlink_to(self.script)
        # The good fake Node delegates to Python to execute the fake CLI script.
        self.write_executable(self.bin/'node', '#!'+sys.executable+'\n'+
            "import os,sys\nif sys.argv[1:]==['--version']:\n print('v22.23.2');sys.exit(0)\n"+
            "os.execv(sys.executable,[sys.executable]+sys.argv[1:])\n")
        self.write_executable(self.system/'node', '#!'+sys.executable+'\n'+
            "import sys\nprint('v12.22.9' if sys.argv[1:]==['--version'] else 'OLD_NODE_CANNOT_PARSE');sys.exit(42)\n")
        self.write_executable(self.script, '''#!/usr/bin/env node
import json,os,sys
from pathlib import Path
assert Path.cwd().name=='input_only'
assert 'NODE_OPTIONS' not in os.environ and 'EXTRA_SECRET' not in os.environ
a=sys.argv[1:]
if a==['--version']:
 assert sys.stdin.read()==''
 print('codex-cli fixture');sys.exit(0)
if a==['exec','--help']:
 assert sys.stdin.read()==''
 print('Usage: codex exec [OPTIONS] [PROMPT]');sys.exit(0)
context=json.loads(sys.stdin.read())
raw=json.dumps({'context':context,'cwd':str(Path.cwd()),'PATH':os.environ['PATH']})
Path(a[a.index('--output-last-message')+1]).write_text(raw)
print(json.dumps({'type':'fixture_only','text':raw}))
''')
    def tearDown(self):self.tmp.cleanup()
    def write_executable(self,path,text):path.write_text(text);path.chmod(0o700)

    def test_symlink_keeps_new_node_for_preflight_and_actual_worker(self):
        with patch.object(bridge,'SYSTEM_PATH',(str(self.system),)), \
             patch.dict(os.environ,{'NODE_OPTIONS':'BAD','EXTRA_SECRET':'DO_NOT_INHERIT'}):
            pre=self.root/'preflight'
            report=bridge.preflight(self.launcher,pre)
            self.assertEqual(report['status'],'PASS',report)
            self.assertEqual(report['paths']['launcher'],str(self.launcher))
            self.assertEqual(report['paths']['resolved_script'],str(self.script))
            self.assertEqual(report['paths']['node'],str(self.bin/'node'))
            self.assertEqual(report['probes'][0]['stdout'].strip(),'v22.23.2')
            self.assertEqual([r['command'][1:] for r in report['probes']],
                             [['--version'],['--version'],['exec','--help']])
            self.assertEqual(report['model_calls'],0)
            payload={'context':{'fixture':True},'schema':{'type':'object','properties':{
                'context':{'type':'object','properties':{'fixture':{'type':'boolean'}},'required':['fixture'],'additionalProperties':False},
                'cwd':{'type':'string'},'PATH':{'type':'string'}},'required':['context','cwd','PATH'],'additionalProperties':False},
                     'images':[base64.b64encode(PNG).decode()]}
            result=bridge.infer(payload,threading.Event(),executable=self.launcher,
                                run_root=self.root/'worker',timeout_s=5)
            self.assertEqual(result['return_code'],0,result)
            run=Path(result['local_log'])
            observed=json.loads(result['raw'])
            actual=json.loads((run/'environment.json').read_text())
            self.assertEqual(observed['PATH'],report['paths']['PATH'])
            self.assertEqual(observed['cwd'],str(run/'input_only'))
            self.assertEqual(actual['node'],report['paths']['node'])
            self.assertEqual(actual['environment_keys'],report['paths']['environment_keys'])
            # Reproduce the former symlink-resolution bug with the old fake system Node.
            old=bridge.worker_environment(self.launcher,pre)
            old['PATH']=str(self.script_dir)+os.pathsep+str(self.system)
            failed=subprocess.run([str(self.launcher),'--version'],env=old,cwd=pre/'input_only',
                                  stdin=subprocess.DEVNULL,capture_output=True,text=True)
            self.assertEqual(failed.returncode,42)
            self.assertIn('OLD_NODE_CANNOT_PARSE',failed.stdout)

    def test_environment_preserves_only_original_allowlist(self):
        source={key:'fixture' for key in bridge.ENV_ALLOWLIST}
        source.update(PATH='/bad/shell',NODE_OPTIONS='bad',CODEX_HOME='/secret',EXTRA_SECRET='secret')
        with patch.dict(os.environ,source,clear=True):
            env=bridge.worker_environment(self.launcher,self.root)
        self.assertEqual(set(env),set(bridge.ENV_ALLOWLIST)|{'PATH','TMPDIR'})
        self.assertEqual(env['PATH'].split(os.pathsep)[0],str(self.bin))
        self.assertNotIn('/bad/shell',env['PATH'])

    def test_preflight_timeout_records_failure_without_inference(self):
        with patch.object(bridge.subprocess,'run',side_effect=subprocess.TimeoutExpired('node',1)):
            report=bridge.preflight(self.launcher,self.root/'timeout',timeout_s=1)
        self.assertEqual(report['status'],'FAIL')
        self.assertIn('TimeoutExpired',report['error'])
        self.assertEqual(len(report['probes']),1)
        self.assertEqual(report['model_calls'],0)
        self.assertTrue((self.root/'timeout/preflight.json').exists())

    def test_preflight_failure_exits_before_physical_scene(self):
        output=self.root/'blocked'
        argv=['run_sim_placement.py','--assets',str(self.root/'unused-assets'),
              '--output',str(output),'--condition','S','--model','local-cli',
              '--authorize-model','--max-model-requests','1','--codex-executable',str(self.launcher)]
        with patch.object(sys,'argv',argv), \
             patch.object(bridge,'preflight',return_value={'status':'FAIL','model_calls':0}), \
             patch.object(runner,'RM65Backend') as backend, \
             patch.object(runner.importlib.metadata,'version',return_value='fixture'), \
             patch.object(runner.signal,'signal'),contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(),1)
        backend.assert_not_called()
        result=json.loads((output/'result.json').read_text())
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('CLI_PREFLIGHT_FAILED',result['error'])
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(result['hardware_calls'],0)
        self.assertFalse((output/'scene').exists())


if __name__=='__main__':unittest.main()
