#!/usr/bin/env python3
"""Create an explicitly fake Codex CLI, using a hash-identical installed Node binary."""
import argparse,hashlib,json,shutil
from pathlib import Path

def prepare(output,node=Path('/home/alex/.nvm/versions/node/v22.23.2/bin/node')):
    output.mkdir(parents=True,exist_ok=False);(output/'bin').mkdir();(output/'package').mkdir()
    shutil.copy2(node,output/'bin/node')
    script=output/'package/fake.js'
    script.write_text('''#!/usr/bin/env node
const fs=require('fs'); const args=process.argv.slice(2);
if(args.join(' ')==='--version'){console.log('codex-cli FAKE_NOT_ASTRA');process.exit(0);}
if(args.join(' ')==='exec --help'){console.log('Usage: codex exec FAKE');process.exit(0);}
if(fs.existsSync('/home/alex/astra-realman_ws')||fs.existsSync('/home/alex/.codex/auth.json'))throw Error('ISOLATION');
if(!args.includes('model_reasoning_effort="medium"')||args[args.indexOf('--model')+1]!=='gpt-6-astra')throw Error('CONFIG');
const w=JSON.parse(fs.readFileSync(0,'utf8'));
if(JSON.stringify(w).includes('PRIVATE_SENTINEL')||JSON.stringify(w).includes('relative_lift_after_closure'))throw Error('PRIVATE_INPUT');
const c={kind:'candidate',binding:w.binding,operation:'chunk',actions:[{type:'hold',seconds:0.04}],requirements:['scene_healthy'],evidence_refs:[w.attachments[0].id],parent_evidence_hash:w.evidence_packet_hash,verdict:null,reason:'FAKE_PROCESS_RAW_NOT_ASTRA'};
fs.writeFileSync(args[args.indexOf('--output-last-message')+1],JSON.stringify(c));
console.log(JSON.stringify({type:'turn.completed',usage:{input_tokens:3,cached_input_tokens:0,output_tokens:2,fixture_only:true}}));
''');script.chmod(0o755);(output/'bin/codex').symlink_to('../package/fake.js')
    (output/'fixture.json').write_text(json.dumps({'source':'FAKE_CLI_NOT_ASTRA','node_source':str(node),'node_sha256':hashlib.sha256(node.read_bytes()).hexdigest(),'real_model_calls':0},indent=2))
    return output/'bin/codex'
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(prepare(a.output))
