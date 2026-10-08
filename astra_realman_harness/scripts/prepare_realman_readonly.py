#!/usr/bin/env python3
"""Default static readiness report. Optional explicitly enabled single-arm SDK read.
No action/gripper/fault-clear command path; no motion authorization is created.
"""
import argparse,hashlib,ipaddress,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from realman_api2_readonly import SDKReadOnly,SDK_SOURCE,SDK_LIBRARY
from io_utils import output_path

def inspect_config(cfg):
    errors=[]
    if cfg.get('scope')!='READ_ONLY_PREPARATION_NO_MOTION' or cfg.get('execution_permitted') is not False:errors.append('SCOPE')
    if cfg.get('arm') not in ('left','right'):errors.append('ARM_UNKNOWN')
    try:ipaddress.ip_address(cfg['host'])
    except (ValueError,KeyError):errors.append('ENDPOINT_UNKNOWN')
    if type(cfg.get('port')) is not int or not 1<=cfg['port']<=65535:errors.append('PORT_UNKNOWN')
    sources={}
    for key,p in [('sdk_source_sha256',SDK_SOURCE),('sdk_library_sha256',SDK_LIBRARY)]:
        actual=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        sources[str(p)]=actual
        if actual is None or cfg.get(key)!=actual:errors.append(key.upper()+'_MISSING_OR_MISMATCH')
    return {'status':'READ_READY_ONLY' if not errors else 'NOT_READY','blocking':errors,'sdk_files':sources,
        'unknown_parameters':[k for k,v in cfg.items() if v=='UNKNOWN'],
        'hardware_execution':'NOT_AUTHORIZED_NOT_VERIFIED','motion_commands':0,'device_connections':0,'sdk_loaded':False,
        'limitations':'Host receipt timestamps, non-atomic reads. Does not establish work/TCP frame binding, holding, hardware STOP or freshness bounds.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--connect-readonly',action='store_true',help='Requires separately authorized onsite connection; one snapshot, no retries.')
    a=p.parse_args();cfg=json.loads(a.config.read_text());report=inspect_config(cfg)
    if a.connect_readonly:
        output_path(a.output) # existing SDK journal confines output to the harness directory
    a.output.mkdir(parents=True,exist_ok=False)
    if a.connect_readonly and report['status']=='READ_READY_ONLY':
        sdkdir=a.output/'sdk';sdkdir.mkdir();session=SDKReadOnly(sdkdir)
        try:
            with session:
                report['sdk_loaded']=True;report['device_connections']=1
                connection=session.connect(cfg['arm'],cfg['host'],cfg['port'],dof=6);report['connection']=connection
                if not connection['connected']:raise RuntimeError('CONNECT_FAILED_NO_RETRY')
                report['snapshot']=session.snapshot(cfg['arm'])
                report['status']='READ_COMPLETED' if report['snapshot']['canonical'] is not None else 'READ_FAILED'
        except Exception as exc:report.update(status='READ_FAILED',error=repr(exc))
        finally:report['sdk_events']=session.events
    elif a.connect_readonly:report['connect_refused']=True
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'output':str(a.output),'device_connections':report['device_connections']}))
    return 0 if report['status'] in ('READ_READY_ONLY','READ_COMPLETED') else 2
if __name__=='__main__':raise SystemExit(main())
