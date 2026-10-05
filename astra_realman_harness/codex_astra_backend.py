"""Official Mac Codex decision transport. No robot imports or execution calls."""
import base64
import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from decision_backends import BackendFailure, check_events
from io_utils import ROOT, write_json

class CodexAstraBackend:
    def __init__(self, config, run, model, stop, emit, schema, parser):
        self.config, self.run, self.model = config, Path(run), model
        self.stop, self.emit, self.schema, self.parser = stop, emit, Path(schema), parser
        self.raw = None

    def decide(self, context, images):
        started = time.monotonic()
        meta = {'backend':'CodexAstraBackend','model':self.model,'provider':'openai',
                'auth':'Mac ChatGPT login','status':'STARTED'}
        request_id = uuid.uuid4().hex
        endpoint = self.config['bridge_url']
        token = ''
        def request(route, value, timeout):
            req = urllib.request.Request(endpoint+route, data=json.dumps(value,allow_nan=False).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
            with urllib.request.urlopen(req,timeout=timeout) as response:
                return json.loads(response.read(4*1024*1024+1))
        try:
            if endpoint != 'http://127.0.0.1:18766' or self.model != 'gpt-6-astra':
                raise BackendFailure('CODEX_ASTRA_CONFIG_INVALID')
            token = (ROOT/'config/codex_astra_bridge.token').read_text().strip()
            if images != context['images_in_attachment_order']:
                raise BackendFailure('CODEX_ASTRA_IMAGES_CONTEXT_MISMATCH')
            if self.stop.is_set():raise BackendFailure('CODEX_ASTRA_CANCELLED')
            attachments=[]
            for item in images:
                path=Path(item['image_path']).resolve()
                if not path.is_relative_to((ROOT/'logs').resolve()):
                    raise BackendFailure('CODEX_ASTRA_IMAGE_OUTSIDE_LOGS')
                data=path.read_bytes()
                if len(data)>8*1024*1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise BackendFailure('CODEX_ASTRA_IMAGE_INVALID')
                attachments.append(base64.b64encode(data).decode())
            # JSON object is preserved; attachment paths in context stay remote paths.
            prompt=json.dumps(context,ensure_ascii=False,allow_nan=False)
            (self.run/'prompt.txt').write_text(prompt)
            payload={'request_id':request_id,'context':context,'images':attachments,
                     'schema':json.loads(self.schema.read_text())}
            box={}
            def invoke():
                try:box['response']=request('/decide',payload,self.config['timeout_s']+5)
                except Exception as exc:box['error']=type(exc).__name__+':'+str(exc)
            thread=threading.Thread(target=invoke,daemon=True);thread.start();notified=0
            while thread.is_alive():
                elapsed=time.monotonic()-started
                if self.stop.is_set() or elapsed>self.config['timeout_s']:
                    try:request('/cancel',{'request_id':request_id},2)
                    except Exception:pass
                    raise BackendFailure('CODEX_ASTRA_CANCELLED' if self.stop.is_set() else 'CODEX_ASTRA_TIMEOUT')
                if elapsed>=notified+5:
                    self.emit('ASTRA STATUS',{'status':'inference running','backend':'CodexAstraBackend','elapsed_s':round(elapsed,1)})
                    notified=elapsed
                self.stop.wait(.1)
            if 'error' in box:raise BackendFailure('CODEX_ASTRA_TRANSPORT_ERROR',box)
            response=box['response']
            for key,name in [('events','events.jsonl'),('stderr','stderr.log'),('raw','astra_raw.txt')]:
                if isinstance(response.get(key),str):(self.run/name).write_text(response[key])
            if 'command' in response:write_json(self.run/'command.json',response['command'])
            meta.update(cli_return_code=response.get('return_code'),local_log=response.get('local_log'),
                        cli_latency_s=response.get('latency_s'))
            if response.get('error') or response.get('return_code')!=0:
                raise BackendFailure('CODEX_ASTRA_CALL_FAILED',{'detail':response.get('error')})
            # Only adapt the known startup notice's host path for the existing audit.
            events=[]
            for line in response['events'].splitlines():
                event=json.loads(line);item=event.get('item',{})
                old='in '+response.get('mac_home','')+'/.codex/config.toml.'
                if item.get('type')=='error' and item.get('message','').startswith('Under-development features enabled: skip_host_skill_discovery. '):
                    item['message']=item['message'].replace(old,'in /home/tongji/.codex/config.toml.')
                events.append(json.dumps(event))
            final=check_events('\n'.join(events))
            self.raw=response['raw']
            if len(self.raw)>65536 or self.raw.strip()!=final.strip():
                raise BackendFailure('CODEX_ASTRA_OUTPUT_MISMATCH')
            action=self.parser(self.raw)
            (self.run/'last_message.json').write_text(self.raw)
            self.emit('ASTRA RAW OUTPUT',self.raw)
            meta['status']='COMPLETE'
            return action
        except BackendFailure as exc:
            meta.update(status='FAILED',error=exc.code);raise
        except Exception as exc:
            meta.update(status='FAILED',error=type(exc).__name__+':'+str(exc))
            raise BackendFailure('CODEX_ASTRA_BACKEND_ERROR',meta) from exc
        finally:
            meta['inference_latency_s']=time.monotonic()-started
            write_json(self.run/'backend_result.json',meta)
