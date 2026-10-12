"""Classify paired network probes without assuming every routing error is a proxy failure."""
import argparse
import json
from pathlib import Path


def https_ready(case):
    probes=case.get('result',{}).get('probes',[])
    https=[r for r in probes if r.get('kind')=='https_get_no_auth']
    return len(https)==2 and all(r.get('status')=='HTTP_RESPONSE' for r in https)


def classify(managed,host):
    m={c['name']:c for c in managed['cases']};h={c['name']:c for c in host['cases']}
    if not https_ready(m['worker_filtered']) and not https_ready(m['worker_https_proxy_candidate']) and https_ready(h['worker_filtered']):
        status='OUTER_EXECUTION_NETWORK_BOUNDARY_CONFIRMED'
        action='Use approved host network access for the launcher; preserve original inner bwrap and env allowlist.'
    elif not https_ready(h['worker_filtered']) and https_ready(h['worker_https_proxy_candidate']):
        status='HTTPS_PROXY_FORWARDING_NECESSARY_IN_TESTED_HOST'
        action='Review the tested HTTPS proxy variables for a minimal production allowlist update.'
    elif https_ready(m['worker_filtered']) and https_ready(h['worker_filtered']):
        status='NETWORK_TRANSPORT_READY_ROUTING_AND_AUTH_REQUIRE_SEPARATE_CHECK'
        action='Inspect native CLI workspace discovery and login state without assuming proxy failure.'
    else:
        status='UNRESOLVED_TRANSPORT_LAYER'
        action='Inspect per-layer DNS, TCP and verified TLS failures; do not consume model requests.'
    return {'status':status,'action':action,'inference_requests':0,
            'production_proxy_allowlist_change_required':status=='HTTPS_PROXY_FORWARDING_NECESSARY_IN_TESTED_HOST',
            'matrix':{group:{c['name']:{'network_namespace':c.get('result',{}).get('network_namespace'),
                'https_ready':https_ready(c),'tls_results':[r for r in c.get('result',{}).get('probes',[]) if r.get('kind')=='https_get_no_auth']}
                for c in data['cases']} for group,data in (('managed',managed),('actual_host',host))}}


def catalog_has_remote_evidence(result):
    """Exit 0 and an Astra slug in a bundled catalog do not prove server connectivity."""
    return result.get('return_code')==0 and result.get('same_as_bundled') is False and not result.get('refresh_error_logged',True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--managed',type=Path,required=True);p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=classify(json.loads(a.managed.read_text()),json.loads(a.host.read_text()))
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
