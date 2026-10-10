"""Actual isolated worker/bridge with FAKE CLI, real frozen inputs. No network/auth."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from platform_v1.research.broker import Broker
from platform_v1.research.action_proposal import proposal_request
from candidate_update_fixtures import sealed_store
from scripts.prepare_research_fake_cli import prepare
from sim_skills.full_pnp.infer_process import InferConfig

JS=r'''#!/usr/bin/env node
const fs=require('fs'),crypto=require('crypto'),path=require('path'),cp=require('child_process');
const a=process.argv.slice(2),w=JSON.parse(fs.readFileSync(0,'utf8'));
if(fs.existsSync('/home/alex/.codex/auth.json')||fs.existsSync('/home/alex/astra-realman_ws/semantic-grounding-authorized-01-20261010'))throw Error('PRIVATE_MOUNT');
const s=a[a.indexOf('--output-schema')+1];
const checked=cp.spawnSync(PYTHON,['-B','-c',"import sys,json;sys.path.insert(0,'/code');from structured_outputs import check_provider;check_provider(json.load(open(sys.argv[1])))",s]);
if(checked.status!==0)throw Error('STRICT_SCHEMA_REJECTED:'+checked.stderr);
const schema=JSON.parse(fs.readFileSync(s));
if(schema.properties.result.properties.version.enum[0]!=='astra.action_proposal.v1')throw Error('WRONG_SCHEMA');
const hashes=[];for(let i=0;i<a.length;i++)if(a[i]==='--image')hashes.push(crypto.createHash('sha256').update(fs.readFileSync(a[i+1])).digest('hex'));
if(hashes.length!==3||JSON.stringify(hashes)!==JSON.stringify(w.attachments.map(x=>x.sha256)))throw Error('IMAGES');
const mode=JSON.parse(fs.readFileSync(path.join(__dirname,'../fixture.json'))).mode;
const origin=w.action_proposal_host.plan_fields.origin_pose_world;
const result={version:'astra.action_proposal.v1',decision:mode==='malformed'?'planned':mode,proposal:null,reason:'FAKE_CLI_NOT_ASTRA',assumptions:['FAKE review hypothesis'],unknowns:['clearance unknown'],additional_claims:[]};
if(result.decision==='planned')result.proposal={waypoints:Array.from({length:4},(_,j)=>({index:j+1,type:'move_pose',pose:origin.map((x,k)=>k===0?x+.025*(j+1):x),nominal_end_offset_s:2*(j+1),prediction_dependencies:Array.from({length:j},(_,k)=>k+1),boundary_after:'none'})),termination:{kind:'horizon_filled',reason:'FAKE software test'}};
if(mode==='malformed')result.origin_pose_world=origin;
console.log(JSON.stringify({type:'fixture.received',source:'FAKE_CLI_NOT_REAL_PROVIDER',strict_schema_checked:true,images:hashes,schema_sha256:crypto.createHash('sha256').update(fs.readFileSync(s)).digest('hex'),instruction:w.instruction}));
fs.writeFileSync(a[a.indexOf('--output-last-message')+1],JSON.stringify({evidence_refs:[...w.attachments.map(x=>x.id),...w.binding.evidence_ids],result}));
console.log(JSON.stringify({type:'turn.completed'})); // deliberately missing usage
'''

class ProposalCLITests(unittest.TestCase):
    def test_real_worker_bridge_production_schema_fake_cli(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(os.environ.get('ACTION_PROPOSAL_CLI_ARTIFACTS',t));root.mkdir(exist_ok=True,parents=True)
            launcher=prepare(root/'cli');(launcher.parent.parent/'package/fake.js').write_text(JS.replace('PYTHON',json.dumps(sys.executable)))
            store,o,w,cfg=sealed_store()
            b=Broker(root/'broker',store,InferConfig(str(launcher),fixture=True),deadline=time.monotonic()+90,
                epoch=lambda:o['execution_epoch'],allowance=lambda:4,baseline_busy=lambda:False,emit=lambda *x:None)
            for mode in ('planned','refused','need_more_evidence','malformed'):
                (launcher.parent.parent/'fixture.json').write_text(json.dumps({'mode':mode}))
                rid=b.submit(proposal_request(w,o))['request_id']
                until=time.monotonic()+20
                while b.job and time.monotonic()<until:b.tick();time.sleep(.01)
                self.assertIsNone(b.job);row=b.rows[rid]
                self.assertEqual(row['status'],'FAILED' if mode=='malformed' else 'READY',row['error'])
                self.assertIsNone(row['usage_raw']);self.assertIsNone(b.action_ready)
                self.assertEqual(row['provenance'],'FAKE_MODEL_RAW')
                event=next(json.loads(x) for x in row['worker_record']['events'].splitlines() if json.loads(x).get('type')=='fixture.received')
                self.assertTrue(event['strict_schema_checked']);self.assertEqual(len(event['images']),3)
                if mode=='malformed':self.assertIn('LOCAL_OUTPUT_VALIDATION',json.dumps(row['worker_record']));self.assertNotIn('derived_shadow',row)
            self.assertEqual(b.calls,4);self.assertEqual(b.infer_calls,4)
            (root/'RESULT.json').write_text(json.dumps({'source':'FAKE_CLI_ONLY','cases':4,'real_model_calls':0,'network':'unshare-all','auth':'not mounted','physical_calls':0},indent=2))

if __name__=='__main__':unittest.main(verbosity=2)
