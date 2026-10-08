"""Minimal CLI worker sandbox; no scene, scores, policy code or service entrypoint."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from scripts.codex_astra_mac_bridge import worker_environment

CLI='/home/alex/.nvm/versions/node/v22.23.2/bin/codex'


@dataclass(frozen=True)
class InferConfig:
    executable: str = CLI
    # Fixtures use the same process path with no auth and no network.
    fixture: bool = False

    @property
    def source(self):return 'FAKE_CLI_PROCESS_NOT_ASTRA' if self.fixture else 'LOCAL_CODEX_ASTRA_RAW'


def sandbox_command(run,config):
    run=Path(run).resolve();inp=run/'input_only';code=run/'worker_code';out=run/'infer_output'
    code.mkdir(exist_ok=True);out.mkdir(exist_ok=True)
    for src,name in ((Path(__file__).with_name('infer_worker.py'),'infer_worker.py'),
                     (Path(__file__).with_name('timing.py'),'timing.py'),
                     (Path(__file__).resolve().parents[2]/'scripts/codex_astra_mac_bridge.py','bridge.py')):
        (code/name).write_bytes(src.read_bytes());(code/name).chmod(0o444)
    launcher=Path(config.executable).expanduser().absolute()
    prefix=launcher.parent.parent
    if launcher.parent.name!='bin' or not launcher.resolve().is_relative_to(prefix):
        raise ValueError('CLI_MUST_STAY_WITHIN_CONFIGURED_NODE_PREFIX')
    venv=str(Path(sys.prefix).resolve())
    cmd=['/usr/bin/bwrap','--tmpfs','/tmp','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
         '--ro-bind',venv,venv,'--ro-bind',str(prefix),str(prefix),
         '--ro-bind',str(inp),'/input','--ro-bind',str(code),'/code','--bind',str(out),'/output',
         '--proc','/proc','--dev','/dev','--unshare-all','--die-with-parent','--new-session']
    if not config.fixture:
        # Reuse existing auth in place, never copy it into an evidence directory.
        auth=Path.home()/'.codex/auth.json'
        if not auth.is_file():raise ValueError('LOCAL_CODEX_AUTH_MISSING')
        cmd+=['--ro-bind',str(auth),str(auth),'--share-net']
        for name in ('resolv.conf','hosts','nsswitch.conf','ssl/certs'):
            path=Path('/etc')/name
            if path.exists():cmd+=['--ro-bind',str(path.resolve()),str(path)]
        for key in ('SSL_CERT_FILE','SSL_CERT_DIR'):
            if os.environ.get(key):
                path=Path(os.environ[key]).resolve()
                if not path.is_relative_to('/etc/ssl/certs'):
                    raise ValueError('NONSTANDARD_CERT_PATH_NOT_MOUNTED:'+key)
    cmd+=['--chdir','/input','--setenv','TMPDIR','/tmp',sys.executable,'-B','/code/infer_worker.py',
          '--executable',str(launcher)]
    return cmd,worker_environment(launcher,run)


def isolated_preflight(config,output):
    """Exactly the infer sandbox/env, but only Node/Codex version and exec help."""
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    (root/'input_only').mkdir();(root/'runtime').mkdir()
    report={'status':'FAIL','model_calls':0,'source':config.source}
    try:
        cmd,env=sandbox_command(root,config);cmd+=['--preflight']
        (root/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
        proc=subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,cwd=root/'input_only',timeout=50)
        (root/'stdout.json').write_text(proc.stdout);(root/'stderr.log').write_text(proc.stderr)
        report.update(return_code=proc.returncode,worker=json.loads(proc.stdout))
        if proc.returncode==0 and report['worker']['status']=='PASS':report['status']='PASS'
    except Exception as exc:report['error']=repr(exc)
    (root/'preflight.json').write_text(json.dumps(report,indent=2)+'\n');return report
