"""Replay exact archived raw through Broker in fake job; not a new model result."""
import json,time,hashlib
from types import SimpleNamespace
from unittest.mock import patch
from scripts.replay_postcontact_store import restore
from scripts.diagnose_postcontact_offline import ROOT,OUT,read,save
from platform_v1.research.broker import Broker
from platform_v1.research import pnp_proposal
class LocalReplayJob:
 def __init__(self,*a,**kw):self.proc=SimpleNamespace(pid=-1);self.result=None
 def poll(self):return self.result
for name in ('current_rgbd_h4','persistent_wh_h4'):
 p=ROOT/name;store,w=restore(name,through_close=True);o=store.get(w['state']['observation_id'])
 rawfile=next((p/'episode/private/research_broker/broker-004').glob('infer_output/bridge/*/result.json'));raw=read(rawfile)['raw']
 b=Broker(OUT/name/'raw_replay_broker',store,SimpleNamespace(fixture=True),deadline=time.monotonic()+120,epoch=lambda:o['execution_epoch'],allowance=lambda:1,baseline_busy=lambda:False,emit=lambda *x:None)
 b.pnp_episode_authorization=store.episode_id
 with patch('platform_v1.research.broker.ProcessJob',LocalReplayJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
  rid=b.submit(pnp_proposal.request(w,o))['request_id']
 record={'raw':raw,'usage':None,'usage_events':[],'return_code':0,'error':None,'source':'OFFLINE_REPLAY_OF_FROZEN_RAW_NOT_NEW_MODEL'}
 b.job[1].result={'bytes':json.dumps(record).encode(),'return_code':0,'cancel_reason':None};b.tick();r=b.rows[rid]
 assert r['status']=='READY',(r['status'],r['error']);assert r['raw']==raw and r['parsed']==json.loads(raw)
 assert r['pnp_candidate']['actions']==[] and r['pnp_candidate']['plan'] is None and r['execution_class']=='RECOVERY_ONLY' and b.action_ready is None and r['grants_execution'] is False
 save(OUT/name/'RAW_REPLAY_RESULT.json',{'scope':'OFFLINE_REPLAY_NOT_NEW_MODEL_SUCCESS','frozen_status_unchanged':'FAIL_STOP_PNP_MISSING_SEMANTIC_SOURCE','new_parser_status':r['status'],'raw_utf8_sha256':hashlib.sha256(raw.encode()).hexdigest(),'original_raw_file':str(rawfile),'raw_unmodified':True,'decision':r['parsed']['result']['decision'],'reason':r['parsed']['result']['reason'],'execution_class':r['execution_class'],'derived':r['pnp_candidate'],'action_ready':b.action_ready,'model_calls':0,'owner_calls':0,'episode':0})
 print(name,r['status'],r['execution_class'])
