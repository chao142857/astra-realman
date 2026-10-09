"""ENGINEERING_REFERENCE ONLY. Known reference answers, never mounted into model worker.
This file is a data/transport acceptance fixture, not a research policy or Astra action.
"""
import sys
from pathlib import Path
from platform_client import Client,PlatformError
p=Client();obs=p.reset()
assert not Path('/home/alex/astra-realman_ws').exists()
assert not Path('/private').exists()
for c in ('assembly','fixed','wrist'):p.rgb(obs,c)
try:p.call('score_private')
except PlatformError:pass
else:raise AssertionError('PRIVATE_SCORE_EXPOSED')
def execute(actions):
 global obs
 r=p.execute(actions,obs['observation_id']);assert r['ok'],r
 assert r['unexecuted_count']==0
 obs=p.observe()
def pose(x,y,z):return {'type':'move_pose','pose':[x,y,z,0,1,0,0]}
execute([pose(.36,-.06,.18),pose(.36,-.06,.08),pose(.36,-.06,.04)])
execute([{'type':'gripper','opening':.45}])
x,y,z=obs['state']['actual_grasp_center_world']
execute([pose(x,y,z+.08),{'type':'hold','seconds':1.2}])
execute([pose(.36,.17,.12)]);execute([pose(.36,.17,.04)])
execute([{'type':'gripper','opening':1.}]);execute([pose(.36,.17,.12)])
# Exercise the SAME infer bridge with one fake raw hold proposal; no target answers supplied.
proposal=p.infer(obs['observation_id']);c=proposal['candidate']
assert c['operation']=='chunk' and c['actions']==[{'type':'hold','seconds':.04}]
r=p.execute(c['actions'],obs['observation_id'],proposal['proposal_id']);assert r['ok'],r
fresh=p.observe();assert fresh['state']['sim_step']>obs['state']['sim_step'];assert fresh['observation_id']!=obs['observation_id']
assert not Path('/home/alex/.codex/auth.json').exists()
print('ENGINEERING_REFERENCE_AND_FAKE_RAW_TO_ACTION_TO_FRESH_RGB_OK',file=sys.stderr)
p.finish('done')
