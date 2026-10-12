"""Read-only, unauthenticated HTTPS diagnostics. Never calls an inference endpoint."""
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

TARGETS=('https://chatgpt.com/backend-api/codex/models?client_version=0.162.1',
         'https://api.openai.com/v1/models')
PROXY_KEYS=('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy','ALL_PROXY','all_proxy','NO_PROXY','no_proxy')

def proxy_summary(env):
    result={}
    for name in PROXY_KEYS:
        if name not in env:continue
        value=env[name]
        if name.lower()=='no_proxy':result[name]={'value':value};continue
        p=urllib.parse.urlsplit(value)
        result[name]={'scheme':p.scheme,'hostname':p.hostname,'port':p.port,
                      'credentials_present':p.username is not None or p.password is not None}
    return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):return None


def main():
    result={'inference_requests':0,'authenticated_requests':0,'network_namespace':os.readlink('/proc/self/ns/net'),
            'environment_keys':sorted(os.environ),'proxy_configuration':proxy_summary(os.environ),
            'dns_configuration':Path('/etc/resolv.conf').read_text(),
            'ca_bundle_sha256':hashlib.sha256(Path('/etc/ssl/certs/ca-certificates.crt').read_bytes()).hexdigest(),
            'tls_default_verify_paths':ssl.get_default_verify_paths()._asdict(),'probes':[],
            'gt_mount_checks':{p:Path(p).exists() for p in ('/home/alex/astra-realman_ws','/home/alex/astra_spatial_capability','/input/ground_truth.json','/code/scoring.py')},
            'user_config_mounted':Path('/home/alex/.codex/config.toml').exists()}
    for host in ('chatgpt.com','api.openai.com'):
        r={'kind':'dns','host':host};start=time.monotonic()
        try:r['addresses']=sorted({x[4][0] for x in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)});r['status']='PASS'
        except OSError as e:r.update(status='FAIL',error_type=type(e).__name__,errno=e.errno)
        r['latency_s']=time.monotonic()-start;result['probes'].append(r)
    for host,port in (('127.0.0.1',7897),('chatgpt.com',443),('api.openai.com',443)):
        r={'kind':'tcp','host':host,'port':port};start=time.monotonic()
        try:
            with socket.create_connection((host,port),timeout=3):r['status']='PASS'
        except OSError as e:r.update(status='FAIL',error_type=type(e).__name__,errno=e.errno)
        r['latency_s']=time.monotonic()-start;result['probes'].append(r)
    for url in TARGETS:
        r={'kind':'https_get_no_auth','url':url,'tls_verification_enabled':True};start=time.monotonic()
        # A HTTP response (including 401/403) establishes transport, not account entitlement.
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        req=urllib.request.Request(url,headers={'User-Agent':'astra-network-diagnostic/0','Accept':'application/json'})
        try:
            with opener.open(req,timeout=5) as response:
                body=response.read(512);r.update(status='HTTP_RESPONSE',http_status=response.status,body_prefix_sha256=hashlib.sha256(body).hexdigest())
        except urllib.error.HTTPError as e:
            body=e.read(512);r.update(status='HTTP_RESPONSE',http_status=e.code,body_prefix_sha256=hashlib.sha256(body).hexdigest())
        except (OSError,urllib.error.URLError) as e:
            cause=getattr(e,'reason',e);r.update(status='FAIL',error_type=type(cause).__name__,errno=getattr(cause,'errno',None))
        r['latency_s']=time.monotonic()-start;result['probes'].append(r)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
