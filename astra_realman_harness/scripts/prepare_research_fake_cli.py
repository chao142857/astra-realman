#!/usr/bin/env python3
"""Offline dynamic-role fixture; real Node, fake Codex, no parent/child model claims."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.prepare_platform_fake_cli import prepare as base_prepare

JS = r'''#!/usr/bin/env node
const fs=require('fs'), crypto=require('crypto'); const a=process.argv.slice(2);
if(a.join(' ')==='--version'){console.log('codex-cli FAKE_RESEARCH_NOT_ASTRA');process.exit(0);}
if(a.join(' ')==='exec --help'){console.log('Usage: codex exec FAKE');process.exit(0);}
if(fs.existsSync('/home/alex/astra-realman_ws')||fs.existsSync('/home/alex/.codex/auth.json'))throw Error('PRIVATE_MOUNT');
if(!a.includes('model_reasoning_effort="medium"')||a[a.indexOf('--model')+1]!=='gpt-6-astra'||!a.includes('multi_agent'))throw Error('CONFIG');
const cfg=JSON.parse(fs.readFileSync(require('path').join(__dirname,'../fixture.json'))), w=JSON.parse(fs.readFileSync(0,'utf8'));
const schema=fs.readFileSync(a[a.indexOf('--output-schema')+1]);
const imageHashes=[];
for(let i=0;i<a.length;i++)if(a[i]==='--image')imageHashes.push(crypto.createHash('sha256').update(fs.readFileSync(a[i+1])).digest('hex'));
if(JSON.stringify(imageHashes)!==JSON.stringify(w.attachments.map(x=>x.sha256)))throw Error('IMAGE_ROUTING');
console.log(JSON.stringify({type:'fixture.received',role:w.role,images:imageHashes,schema_sha256:crypto.createHash('sha256').update(schema).digest('hex'),native_subagent:false}));
const output=a[a.indexOf('--output-last-message')+1];
if(cfg.mode==='api'){console.error('FAKE_API_ERROR');process.exit(17);}
if(cfg.mode==='partial'){fs.writeFileSync(output,'{"partial":');setTimeout(()=>{},60000);}
else setTimeout(()=>{
 let result;
 if(w.role==='action')result={version:'astra.action_chunk_plan.v1',H:8,waypoints:Array.from({length:8},()=>({type:'hold',seconds:0.02})),world_id:w.binding.world_id,world_revision:w.binding.world_revision,source_observation_id:w.binding.observation_ids.at(-1),execution_epoch:w.binding.execution_epoch,task_binding:{profile:'scene_only_v1',object_id:'',goal_id:''},semantics:'PREDICTED_WAYPOINTS_NOT_MEASURED'};
 else result={regions:w.attachments.map(x=>({entity_id:'fixture-object',label:'FAKE_LABEL',attachment_id:x.id,bbox:cfg.mode==='clipped'?[0,0.25,0.75,0.75]:[0.25,0.25,0.75,0.75],identity_status:'hypothesis'})),association:null};
 const shape=JSON.parse(schema).properties.result;
 if(shape.properties?.version?.const==='astra.semantic_scene.v2'){
   result={version:'astra.semantic_scene.v2',task_target_id:'fixture-object',entities:[
     {entity_id:'fixture-object',label:'FAKE_RED_BLOCK',kind:'object',identity_status:'hypothesis',description:'SYNTHETIC_SCHEMA_FIXTURE_NOT_MODEL_PERCEPTION',views:w.attachments.map(x=>({attachment_id:x.id,bbox:[.2,.2,.8,.8],visibility:'visible'}))},
     {entity_id:'fixture-region',label:'FAKE_REGION',kind:'region',identity_status:'unknown',description:'UNKNOWN_FIXTURE',views:[]}
   ],relations:[],unknowns:['SYNTHETIC_NOT_PHYSICAL_EPISODE']};
 }
 if(shape.properties?.version?.const==='astra.action_chunk_plan.v2'){
   result={};for(const [key,value] of Object.entries(shape.properties))if('const' in value)result[key]=value.const;
   const n=cfg.mode==='terminal'?2:result.H;
   result.waypoints=Array.from({length:n},(_,i)=>({index:i+1,type:'move_pose',pose:result.origin_pose_world.map((v,j)=>j===0?v+.03*(i+1):v),nominal_end_offset_s:2*(i+1),preconditions:shape.properties.waypoints.items.properties.preconditions.const,prediction_dependencies:Array.from({length:i},(_,j)=>j+1),boundary_after:cfg.mode==='terminal'&&i===n-1?'precontact_handoff':'none'}));
   result.termination={kind:cfg.mode==='terminal'?'stage_terminal':'horizon_filled',reason:'SYNTHETIC_CONTRACT_FIXTURE'};
 }
 const out={binding:w.binding,evidence_refs:[w.attachments[0].id,...w.binding.evidence_ids],result};
 fs.writeFileSync(output,cfg.mode==='malformed'?'{broken':JSON.stringify(out));
 console.log(JSON.stringify({type:'turn.completed',usage:{input_tokens:11,cached_input_tokens:3,output_tokens:7,output_tokens_details:{reasoning_tokens:2},fixture_only:true}}));
},cfg.delay_ms||0);
'''

def prepare(output):
    launcher=base_prepare(output)
    (output/'package/fake.js').write_text(JS)
    p=output/'fixture.json';r=json.loads(p.read_text());r.update(mode='normal',delay_ms=0);p.write_text(json.dumps(r,indent=2))
    return launcher
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args();print(prepare(a.output))
