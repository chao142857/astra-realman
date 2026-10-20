"""Native MCP reads recorded PNGs in place, never the camera or original executor.
Output contains only source hashes, metadata, booleans and counts, no pixels.
"""
import argparse,asyncio,datetime,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src'),str(ROOT/'aspire_realman_phase05/tests')]
from aspire_realman import ReplaySource,CodecConfig,EndpointBinding,build_realman_runtime
from aspire_realman.fixtures import MockSegmentation
from http_support import loopback_server
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import httpx
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--observation',type=pathlib.Path,required=True)
p.add_argument('--assets-root',type=pathlib.Path,required=True)
p.add_argument('--binding-evidence',type=pathlib.Path,required=True)
a=p.parse_args()
def guard(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
  raise PermissionError('Historical replay allows loopback only')
sys.addaudithook(guard)
evidence=a.binding_evidence.read_bytes(); trusted=json.loads(evidence)
reference=trusted.get('controller',trusted).get('before_snapshot',{}).get('canonical')
# The standalone geometry readback has an unambiguous raw before snapshot.
if reference is None and 'before_snapshot' in trusted:reference=trusted['before_snapshot']['canonical']
if reference is None:raise SystemExit('BINDING_REFERENCE_NOT_FOUND')
source=ReplaySource(a.observation,assets_root=a.assets_root);snapshot=source.read();raw=snapshot['canonical_states']['left']
for key in ['work_frame','tool_frame']:
 if raw[key]['definition_fingerprint']!=reference[key]['definition_fingerprint']:
  raise SystemExit('ARCHIVED_WORK_TOOL_BINDING_CHANGED')
binding=EndpointBinding('left',raw['work_frame']['id'],raw['tool_frame']['id'],
 raw['work_frame']['definition_fingerprint'],raw['tool_frame']['definition_fingerprint'],
 str(a.binding_evidence)+':sha256:'+hashlib.sha256(evidence).hexdigest()+':historical zero work/tool numeric binding only')
config=CodecConfig(('left',),raw['work_frame']['id'],{'left':binding})
runtime=build_realman_runtime(source,config,segmentation_provider=MockSegmentation())
result={'timestamp':datetime.datetime.now().astimezone().isoformat(),'mode':'HISTORICAL_REPLAY_IN_PLACE',
 'observation_path':str(a.observation),'observation_sha256':hashlib.sha256(a.observation.read_bytes()).hexdigest(),
 'binding_evidence':str(a.binding_evidence),'binding_evidence_sha256':hashlib.sha256(evidence).hexdigest(),
 'images':[{'serial':c['serial'],'role':c['role'],'sha256':c['sha256'],'shape':list(c['rgb'].shape)} for c in snapshot['cameras']],
 'events':[]}
async def test(base):
 async with httpx.AsyncClient(trust_env=False) as client:
  async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
   async with ClientSession(read,write) as session:
    await session.initialize()
    listing=await session.list_tools();result['tool_names']=[t.name for t in listing.tools]
    for name,args in [('observe',{'cameras':[c['role'] for c in snapshot['cameras']]}),('cap_get_robot_state',{}),('cap_localize_object',{'query':'generic recorded object'}),('cap_set_gripper',{'position':.5,'arm':'left'})]:
     response=await session.call_tool(name,args)
     event={'tool':name,'isError':bool(response.isError),'image_count':sum(c.type=='image' for c in response.content)}
     if name=='observe':
      assert not response.isError and event['image_count']==len(snapshot['cameras'])
      event['stale']=response.structuredContent['observation']['stale'];assert event['stale']
     elif name=='cap_get_robot_state':
      assert not response.isError
      event['base_frame']=response.structuredContent['result']['base_frame'];event['metadata']=response.structuredContent['result']['metadata']
     else:
      assert response.isError
     result['events'].append(event)
try:
 with loopback_server(runtime.app) as base:asyncio.run(test(base))
 result.update(ok=True,physical_commands_sent=runtime.adapter.hardware_commands_sent,camera_pipelines_opened=0,model_requests=0)
finally:runtime.close()
print(json.dumps(result,ensure_ascii=False,indent=2))
