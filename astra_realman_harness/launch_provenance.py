"""Reproducible launch records; no environment or authentication values are recorded."""
import hashlib
import json
import shlex
import subprocess
import sys
from io_utils import ROOT, write_json
from experiment_launch import validate, runner_args


def equivalent_command(settings, python=sys.executable, lock_path=None):
    args=[python,'-I','-B',str(ROOT/'scripts/run_experiment.py')]
    for key,value in validate(settings).items():
        args += ['--'+key.replace('_','-'),str(value)]
    args += ['--no-preview']
    if lock_path:args += ['--lock-path',str(lock_path)]
    return shlex.join(args)


def snapshot(settings, actual_argv, lock_path=None):
    def git(*args):
        try:
            result=subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,text=True)
            return result.stdout if result.returncode==0 else 'UNAVAILABLE'
        except OSError:return 'UNAVAILABLE'
    # Only tracked implementation files; never environment, tokens, recordings or credentials.
    diff=git('diff','HEAD','--','*.py','*.js','*.css','*.html','*.sh')
    revision=git('rev-parse','HEAD').strip()
    if revision=='UNAVAILABLE' and (ROOT/'BUILD_REVISION').is_file():revision=(ROOT/'BUILD_REVISION').read_text().strip()
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*')
            if p.is_file() and not p.is_symlink() and p.suffix in ('.py','.sh','.js','.html','.css')
            and not set(p.relative_to(ROOT).parts)&{'logs','.git','__pycache__','.venv'}}
    return {'implementation_sha256':hashes,'settings':validate(settings),'actual_argv':list(actual_argv),
            'runner_argv':runner_args(settings,no_preview=True,lock_path=lock_path),
            'equivalent_cli':equivalent_command(settings,lock_path=lock_path),
            'git_revision':revision,'implementation_diff':diff,
            'implementation_diff_sha256':hashlib.sha256(diff.encode()).hexdigest(),
            'model':'gpt-6-astra','effort':'medium',
            'camera_configuration':json.loads((ROOT/'config'/('arm_mirror.json' if settings['profile']=='parallel' else 'left_terminal_fourview.json' if settings['profile']=='legacy4' else 'left_terminal.json')).read_text())['cameras'],
            'untracked_implementation_files':git('ls-files','--others','--exclude-standard','--','*.py','*.js','*.css','*.html','*.sh').splitlines()}


class LaunchRecorder:
    """Pass through stdout unchanged; attach provenance when the original runner announces its run."""
    def __init__(self, stream, manifest):self.stream=stream;self.manifest=manifest;self.pending=''
    def write(self, text):
        result=self.stream.write(text);self.pending+=text
        while '\n' in self.pending:
            line,self.pending=self.pending.split('\n',1)
            if line.startswith('RUN → '):
                try:
                    from pathlib import Path
                    path=Path(json.loads(line.split(' → ',1)[1])['log']).resolve()
                    if path.is_relative_to((ROOT/'logs').resolve()) and path.is_dir():
                        write_json(path/'launch_manifest.json',self.manifest)
                except (ValueError,KeyError,OSError):pass
        return result
    def flush(self):return self.stream.flush()
    def __getattr__(self,name):return getattr(self.stream,name)
