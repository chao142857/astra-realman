"""Opt-in live GUI policy. Old experiment event acceptance remains unchanged."""
import json,re
from decision_backends import BackendFailure,check_events


def check_recovered_events(stdout):
    events=[json.loads(line) for line in stdout.splitlines() if line.strip()]
    kinds=[e.get('type') for e in events]
    if any(kinds.count(k)!=1 for k in ('thread.started','turn.started','turn.completed')):
        raise BackendFailure('RECOVERY_AMBIGUOUS_TURN')
    start=kinds.index('turn.started');end=kinds.index('turn.completed')
    if not kinds.index('thread.started')<start<end or end!=len(events)-1:
        raise BackendFailure('RECOVERY_EVENT_ORDER')
    final_indices=[i for i,e in enumerate(events) if e.get('item',{}).get('type')=='agent_message']
    if len(final_indices)!=1 or not start<final_indices[0]<end:
        raise BackendFailure('RECOVERY_AMBIGUOUS_PROPOSAL')
    keep=[];notices=[]
    for i,e in enumerate(events):
        kind=e.get('type');item=e.get('item',{})
        reconnect=kind=='error' and re.fullmatch(r'Reconnecting\.\.\. [1-5]/5 \(stream disconnected before completion: tls handshake eof\)',e.get('message',''))
        fallback=kind=='item.completed' and item.get('type')=='error' and item.get('message')=='Falling back from WebSockets to HTTPS transport. stream disconnected before completion: tls handshake eof'
        if reconnect or fallback:
            if not start<i<final_indices[0]:raise BackendFailure('RECOVERY_LATE_ERROR')
            notices.append(e)
        else:keep.append(e)
    final=check_events('\n'.join(json.dumps(e) for e in keep))
    return final,notices
