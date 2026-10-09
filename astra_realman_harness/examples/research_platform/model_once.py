"""Single raw model proposal, no fallback or retry, and no task target constants.
The owner decides whether the explicitly configured provider is fake or real.
"""
import sys
from platform_client import Client
p=Client();obs=p.reset()
for camera in ('assembly','fixed','wrist'):p.rgb(obs,camera)
proposal=p.infer(obs['observation_id']);candidate=proposal['candidate']
if candidate['operation']!='stop':
    feedback=p.commit(proposal['proposal_id'])
    print(repr(feedback),file=sys.stderr)
    if candidate['operation']=='chunk':
        if not feedback['ok']:raise SystemExit(0) # owner has stopped; no retry
        obs=p.observe()
        for camera in ('assembly','fixed','wrist'):p.rgb(obs,camera)
    if candidate['operation']!='finish':p.finish('unknown')
