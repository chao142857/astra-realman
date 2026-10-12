"""Validate frozen payload and render native prompt input without generation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    sys.path.insert(0, '/code')
    from bridge import command, validate_payload
    from jsonschema import Draft202012Validator
    from PIL import Image
    payload=json.loads(Path('/input/payload.json').read_text())
    schema, audit, decoded=validate_payload(payload)
    Draft202012Validator.check_schema(schema)
    images=[]
    for attachment, data in zip(payload['context']['attachments'], decoded):
        path=Path('/input')/attachment['file']
        assert path.read_bytes()==data
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            images.append({'path':str(path),'bytes':len(data),'size_px':list(image.size),
                           'mode':image.mode,'sha256':hashlib.sha256(data).hexdigest()})
    out=Path('/output/frozen_input');out.mkdir(exist_ok=False)
    (out/'runtime').mkdir();(out/'input_only').mkdir()
    original=command(out,[],sys.argv[1]);configs=[];i=0
    while i<len(original):
        if original[i] in ('-c','--disable'):configs+=original[i:i+2];i+=2
        else:i+=1
    # debug has no --model option; the same model is selected with its config key.
    cmd=[sys.argv[1],'debug','prompt-input',*configs,'-c','model="gpt-6-astra"']
    for image in images:cmd+=['--image',image['path']]
    prompt=json.dumps(payload['context'],ensure_ascii=False,allow_nan=False)
    cmd+=[prompt]
    start=time.monotonic()
    proc=subprocess.run(cmd,capture_output=True,text=True,env=dict(os.environ),timeout=35,cwd=out/'input_only')
    (out/'native_prompt.stdout').write_text(proc.stdout)
    (out/'native_prompt.stderr').write_text(proc.stderr)
    record={'inference_requests':0,'payload_validation':'PASS','provider_schema_valid':'PASS',
            'image_decode':'PASS','images':images,'schema_audit':audit,
            'native_debug_return_code':proc.returncode,'native_debug_latency_s':time.monotonic()-start,
            'command':cmd,'note':'Debug rendering does not validate server acceptance, latency, or generation.'}
    try:
        rendered=json.loads(proc.stdout)
        record['native_rendered_json']=True
        record['native_rendered_sha256']=hashlib.sha256(proc.stdout.encode()).hexdigest()
        record['rendered_type']=type(rendered).__name__
    except ValueError:
        record['native_rendered_json']=False
    (out/'probe.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
