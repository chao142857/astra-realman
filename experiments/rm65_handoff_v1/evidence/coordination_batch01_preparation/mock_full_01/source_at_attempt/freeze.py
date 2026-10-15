"""Seal the predeclared conditions only after their physical witnesses pass."""
import argparse
import gzip
import json
from pathlib import Path
from transfer_gate import sha,save
from .contract import HERE,ROOT,CONDITIONS
from .gate import hashes


def main():
    p=argparse.ArgumentParser();p.add_argument('--witness-root',type=Path,required=True)
    p.add_argument('--suffix',default='02');p.add_argument('--environment',type=Path,required=True)
    a=p.parse_args();entries={}
    for cid in CONDITIONS:
        folder=a.witness_root/(cid+'_'+a.suffix)
        report=json.loads((folder/'witness_PRIVATE.json').read_text())
        assert report['status']=='PHYSICAL_WITNESS_PASS' and report['score']['pass']
        negative=report['negative_control_PRIVATE'];assert not negative['receipt']['executed'] and negative['physics_steps']==0
        assert 'COLLISION' in json.dumps(negative['receipt'])
        public=json.loads((folder/'public_policy.json').read_text())
        assert public['initial_ready_world_wxyz']==json.loads((HERE/'ready_reference.json').read_text())
        paths=['witness_PRIVATE.json','public_policy.json','configuration.json','execution.mp4','physics.jsonl']
        entries[cid]={'folder':str(folder.relative_to(ROOT)),'sha256':{n:sha(folder/n) for n in paths}}
    env=json.loads(a.environment.read_text())
    save(HERE/'witness_manifest.json',{'scope':'PRIVATE_ENGINEERING_NOT_MODEL_INPUT','witnesses':entries})
    save(HERE/'environment.json',env)
    save(HERE/'freeze.json',{'version':'rm65.coordination.batch01.freeze.v1','baseline':'6afd5a8192829affb44e413af521080ba7667713',
         'source_hashes':hashes(),'real_generation_requests_during_preparation':0,
         'witness_manifest_sha256':sha(HERE/'witness_manifest.json')})
    print('FROZEN',len(hashes()),'source/data hashes; real requests 0')


if __name__=='__main__':main()
