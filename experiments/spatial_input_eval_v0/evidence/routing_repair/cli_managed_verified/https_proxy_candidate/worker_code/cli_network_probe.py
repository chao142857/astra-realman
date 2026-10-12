"""Versions, login status, and model-catalog refresh only. No model generation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,'/code')
from bridge import command


def main():
    output=Path('/output/cli_metadata');output.mkdir(parents=True,exist_ok=False);(output/'runtime').mkdir();(output/'input_only').mkdir()
    executable=sys.argv[1]
    original=command(output,[],executable)
    # Reuse exact original -c / --disable network, model/provider, tool and logging settings.
    configs=[];i=0
    while i<len(original):
        if original[i] in ('-c','--disable'):configs+=original[i:i+2];i+=2
        else:i+=1
    rows=[]
    for name,args in (('version',['--version']),('login_status',['login','status']),('catalog_bundled',['debug','models','--bundled',*configs]),('catalog_refresh',['debug','models',*configs])):
        cmd=[executable,*args];start=time.monotonic()
        p=subprocess.run(cmd,capture_output=True,text=True,env=dict(os.environ),timeout=35,cwd=output/'input_only')
        (output/(name+'.stdout')).write_text(p.stdout);(output/(name+'.stderr')).write_text(p.stderr)
        r={'name':name,'command':cmd,'return_code':p.returncode,'latency_s':time.monotonic()-start,
           'stdout_sha256':hashlib.sha256(p.stdout.encode()).hexdigest(),'stderr':p.stderr,'inference_requests':0}
        if name.startswith('catalog_'):
            try:
                catalog=json.loads(p.stdout);models=catalog.get('models',[]) if isinstance(catalog,dict) else catalog
                r.update(model_count=len(models),astra_present=any(m.get('slug')=='gpt-6-astra' for m in models),
                         refresh_error_logged=any(s in p.stderr.lower() for s in ('failed to refresh','routing discovery failed','error sending request')))
            except (ValueError,TypeError,AttributeError):r['catalog_parse']='INVALID'
            if name=='catalog_refresh':
                r['same_as_bundled']=json.loads((output/'catalog_bundled.stdout').read_text())==catalog
                r['remote_refresh_evidence']='BUNDLED_FALLBACK_NO_REMOTE_PROOF' if r['same_as_bundled'] else 'DIFFERS_FROM_BUNDLED_IN_FRESH_SANDBOX'
        else:r['stdout']=p.stdout
        rows.append(r)
    print(json.dumps({'inference_requests':0,'credential_file_read_only':True,'checks':rows},indent=2))

if __name__=='__main__':main()
