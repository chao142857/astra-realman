import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spatial_eval.adapter import environment_config, environment_sandbox, PARAMETERS


class LabEnvironmentTests(unittest.TestCase):
    def test_only_host_executable_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'environment.json'
            path.write_text(json.dumps({'cli_executable':'/isolated/bin/codex'}))
            with patch.dict('os.environ',{'SPATIAL_EVAL_ENV_CONFIG':str(path)}):
                self.assertEqual(environment_config().executable,'/isolated/bin/codex')
                path.write_text(json.dumps({'cli_executable':'/isolated/bin/codex','model':'other'}))
                with self.assertRaisesRegex(ValueError,'ONLY_CLI_EXECUTABLE'):environment_config()
                path.write_text(json.dumps({'cli_executable':'relative/codex'}))
                with self.assertRaisesRegex(ValueError,'ABSOLUTE_CLI'):environment_config()
        self.assertEqual(PARAMETERS['model'],'gpt-6-astra')
        self.assertEqual(PARAMETERS['model_reasoning_effort'],'medium')

    def test_conda_venv_adds_only_interpreter_runtime(self):
        cmd=['bwrap','--ro-bind','/input','/input','--chdir','/input','python']
        with patch('spatial_eval.adapter.production_imports',return_value=(None,lambda r,c:(cmd.copy(),{}),None,None)), \
             patch('spatial_eval.adapter.environment_config',return_value=object()), \
             patch('spatial_eval.adapter.sys.base_prefix','/runtime/python'), \
             patch('spatial_eval.adapter.sys.prefix','/experiment/.venv'):
            actual,_=environment_sandbox('/experiment/run')
        self.assertEqual(actual,['bwrap','--ro-bind','/input','/input',
                                 '--ro-bind','/runtime/python','/runtime/python','--chdir','/input','python'])


if __name__=='__main__': unittest.main()
