"""Generic frozen-input HTTP transport. No action parser, SDK or model invocation code."""
from dataclasses import dataclass
import hashlib
import http.client
import json
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid

from .adapter import PARAMETERS, prepare
from .inputs import FRAME, validate_task, validate_observations
from .geometry import validate_geometry
from .schema import fields, output_schema, read, strict_json, write

MAX_BODY = 8 * 1024 * 1024


@dataclass(frozen=True)
class MacBridgeConfig:
    endpoint: str
    token_file: Path

    def __post_init__(self):
        url=urlsplit(self.endpoint)
        if (url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password
                or url.path not in ('','/') or url.query or url.fragment or url.port is None):
            raise ValueError('BRIDGE_LOOPBACK_HTTP_ORIGIN_REQUIRED')
        if not Path(self.token_file).is_absolute():raise ValueError('BRIDGE_ABSOLUTE_TOKEN_PATH_REQUIRED')

    @classmethod
    def load(cls,path):
        value=read(path);fields(value,['endpoint','token_file'])
        return cls(value['endpoint'],Path(value['token_file']))


def validate_context(context, images):
    fields(context,['instruction','coordinate_system','task','output_schema','attachments','observations','geometry'])
    if not isinstance(context['instruction'],str):raise ValueError('BRIDGE_INSTRUCTION')
    if context['coordinate_system']!=FRAME:raise ValueError('BRIDGE_FRAME')
    validate_task(context['task'])
    if context['output_schema']!=output_schema(context['task']['kind']):raise ValueError('BRIDGE_OUTPUT_SCHEMA')
    obs=context['observations'];fields(obs,['calibration','robot_state','synchronization'])
    validate_observations(dict(obs,rgb=[],depth=[]))
    if context['geometry'] is not None:validate_geometry(context['geometry'])
    if len(images)!=3 or len(context['attachments'])!=3:raise ValueError('BRIDGE_REQUIRES_THREE_RGB')
    from PIL import Image
    for i,(attachment,path) in enumerate(zip(context['attachments'],images)):
        fields(attachment,['camera_id','file','sha256'])
        if attachment['file']!=f'image-{i}.png':raise ValueError('BRIDGE_ATTACHMENT_NAME')
        data=Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest()!=attachment['sha256']:raise ValueError('FROZEN_IMAGE_HASH')
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>8*1024*1024:raise ValueError('BRIDGE_INVALID_PNG')
        with Image.open(path) as image:image.verify()


def parameter_audit(result):
    cmd=result.get('command')
    if not isinstance(cmd,list) or not all(isinstance(x,str) for x in cmd):return False
    if len(cmd)<2 or cmd[1]!='exec' or cmd.count('--model')!=1:return False
    try:
        model=cmd[cmd.index('--model')+1]
        configs={}
        for i,x in enumerate(cmd[:-1]):
            if x=='-c':
                key,value=cmd[i+1].split('=',1);configs[key]=value
        return (model==PARAMETERS['model'] and '--ephemeral' in cmd and cmd.count('--image')==3
                and json.loads(configs['model_reasoning_effort'])==PARAMETERS['model_reasoning_effort']
                and json.loads(configs['model_provider'])==PARAMETERS['provider'])
    except (ValueError,KeyError,IndexError):return False


def usage_from_events(events):
    rows=[]
    for line in events.splitlines():
        try:value=strict_json(line)
        except ValueError:continue
        if isinstance(value,dict) and 'usage' in value:rows.append(value)
    usage=None
    if len(rows)==1 and isinstance(rows[0]['usage'],dict):
        candidate=rows[0]['usage']
        if any(type(candidate.get(k)) is int and candidate[k]>0 for k in ('input_tokens','output_tokens')):usage=candidate
    return usage,rows


class MacBridgeAdapter:
    def __init__(self,config,*,offline_test=False):
        self.config=config;self.offline_test=offline_test
        if offline_test and urlsplit(config.endpoint).port in (18766,18767):
            raise ValueError('OFFLINE_TEST_FORBIDS_PRODUCTION_BRIDGE_PORTS')

    def _post(self,path,body,token,timeout_s):
        """No proxy, redirect or retry; watchdog bounds the entire exchange."""
        url=urlsplit(self.config.endpoint)
        conn=http.client.HTTPConnection('127.0.0.1',url.port,timeout=timeout_s)
        expired=threading.Event();transport_socket=None
        deadline=time.monotonic()+timeout_s
        def expire():
            expired.set()
            if transport_socket is not None:
                try:transport_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        watchdog=threading.Timer(timeout_s,expire);watchdog.daemon=True
        watchdog.start()
        try:
            conn.connect();transport_socket=conn.sock
            remaining=deadline-time.monotonic()
            if expired.is_set() or remaining<=0:raise TimeoutError('BRIDGE_TOTAL_DEADLINE')
            transport_socket.settimeout(remaining)
            conn.request('POST',path,body=body,headers={'Authorization':'Bearer '+token,
                         'Content-Type':'application/json','Connection':'close'})
            response=conn.getresponse()
            raw=response.read(MAX_BODY+1)
            if expired.is_set():raise TimeoutError('BRIDGE_TOTAL_DEADLINE')
            if len(raw)>MAX_BODY:raise ValueError('BRIDGE_RESPONSE_TOO_LARGE')
            return response.status,raw
        except (TimeoutError,socket.timeout):raise TimeoutError('BRIDGE_TOTAL_DEADLINE') from None
        except (OSError,http.client.HTTPException):
            if expired.is_set():raise TimeoutError('BRIDGE_TOTAL_DEADLINE') from None
            raise
        finally:
            watchdog.cancel();conn.close()

    def infer(self,context,images,folder,*,real=False,timeout_s=90):
        if not real and not self.offline_test:raise ValueError('MAC_BRIDGE_EXPLICIT_REAL_MODE_REQUIRED')
        if real and self.offline_test:raise ValueError('OFFLINE_BRIDGE_CANNOT_CLAIM_REAL_MODEL')
        if not 0<timeout_s<=90:raise ValueError('BRIDGE_TIMEOUT_MUST_BE_BOUNDED_AT_90_SECONDS')
        validate_context(context,images)
        folder=Path(folder).resolve();payload=prepare(context,images,folder,real=True)
        # Generic production payload validation only; never load decision_backends.
        from .adapter import HARNESS
        import sys
        if str(HARNESS) not in sys.path:sys.path.insert(0,str(HARNESS))
        from scripts.codex_astra_mac_bridge import validate_payload
        validate_payload(payload)
        token=Path(self.config.token_file).read_text().strip()
        if len(token)<16 or '\r' in token or '\n' in token:raise ValueError('BRIDGE_TOKEN_INVALID')
        rid=uuid.uuid4().hex;wire=dict(payload,request_id=rid)
        body=json.dumps(wire,ensure_ascii=False,allow_nan=False).encode()
        if len(body)>48*1024*1024:raise ValueError('BRIDGE_REQUEST_TOO_LARGE')
        write(folder/'bridge_request.json',wire)
        transport={'endpoint':self.config.endpoint,'request_id':rid,'timeout_s':timeout_s,
                   'authorization_archived':False,'dispatch_attempts':0,'retries':0,'cancel_attempts':0,
                   'server_generation_requests':'NOT_APPLICABLE_OFFLINE' if self.offline_test else 'UNKNOWN'}
        result={'raw':'','events':'','stderr':'','error':None,'return_code':None,'usage':None,
                'source':'FAKE_MAC_BRIDGE_NOT_ASTRA' if self.offline_test else 'REAL_ASTRA_ATTEMPT',
                'model_calls':0,'usage_status':'NOT_APPLICABLE_MOCK' if self.offline_test else 'UNKNOWN'}
        started=time.monotonic()
        try:
            transport['dispatch_attempts']=1
            result['model_calls']=0 if self.offline_test else 1 # dispatch attempt, not confirmed service generation
            status,raw=self._post('/decide',body,token,timeout_s)
            transport['http_status']=status
            (folder/'http_response_body.bin').write_bytes(raw)
            if status!=200:
                result['error']='MAC_BRIDGE_HTTP_'+str(status)
            else:
                original=strict_json(raw.decode('utf-8'))
                if not isinstance(original,dict):raise ValueError('BRIDGE_RESPONSE_OBJECT_REQUIRED')
                write(folder/'bridge_result.json',original)
                for key in ('raw','events','stderr'):
                    if key in original and not isinstance(original[key],str):raise ValueError('BRIDGE_RESPONSE_STRING:'+key)
                if original.get('error') is not None and not isinstance(original['error'],str):raise ValueError('BRIDGE_ERROR_STRING')
                if original.get('return_code') is not None and type(original['return_code']) is not int:raise ValueError('BRIDGE_RETURN_CODE')
                result.update({k:original.get(k,result[k]) for k in ('raw','events','stderr','error','return_code')})
                if result['return_code']==0 and (result['error'] is None or result['error'].startswith('LOCAL_OUTPUT_VALIDATION:')):
                    valid=parameter_audit(original);transport['remote_model_parameter_audit']='PASS' if valid else 'FAIL'
                    if not valid:result['error']='MAC_BRIDGE_MODEL_PARAMETER_MISMATCH'
                usage,events=usage_from_events(result['events']);result['usage_events']=events
                if not self.offline_test and usage is not None:result.update(usage=usage,usage_status='CLI_REPORTED')
        except TimeoutError:
            result['error']='MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN'
            # Cancellation is a separate non-generating endpoint, never a retry.
            transport['cancel_attempts']=1
            try:
                status,raw=self._post('/cancel',json.dumps({'request_id':rid}).encode(),token,3)
                transport['cancel_http_status']=status
                (folder/'cancel_response_body.bin').write_bytes(raw)
                transport['cancel_note']='Acknowledgement does not prove a remote job existed or stopped.'
            except (OSError,ValueError,http.client.HTTPException):transport['cancel_error']='CANCEL_TRANSPORT_FAILED'
        except (OSError,ValueError,UnicodeError,http.client.HTTPException) as exc:
            # Do not reflect exception text, request headers or credentials into artifacts.
            result['error']='MAC_BRIDGE_PROTOCOL_OR_CONNECTION:'+type(exc).__name__
        finally:
            result['wall_latency_s']=time.monotonic()-started
            write(folder/'transport.json',transport)
            write(folder/'response.json',result)
            (folder/'raw.txt').write_text(result['raw'])
            (folder/'events.jsonl').write_text(result['events'])
            (folder/'stderr.log').write_text(result['stderr'])
        return result
