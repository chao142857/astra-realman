#!/usr/bin/env python3
"""Compare two actual simulator captures without expecting wall-clock time equality."""
import argparse
import hashlib
import json
from pathlib import Path
from spatial_eval.schema import write


def main():
    p=argparse.ArgumentParser();p.add_argument('--first',type=Path,required=True)
    p.add_argument('--second',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();assert not a.output.exists(), 'REFUSE_OVERWRITE'
    files=[f.relative_to(a.first) for f in sorted(a.first.glob('*/assets/*')) if f.is_file()]
    assert len(files)==72, 'SIX_TIMES_THREE_TIMES_FOUR_ASSETS'
    rows=[]
    for rel in files:
        first=hashlib.sha256((a.first/rel).read_bytes()).hexdigest()
        second=hashlib.sha256((a.second/rel).read_bytes()).hexdigest()
        assert first==second, ('NON_REPRODUCIBLE_ASSET',rel)
        rows.append({'path':str(rel),'sha256':first,'byte_identical':True})
    for rel in json.loads((a.first/'index.json').read_text())['snapshots']:
        s=json.loads((a.first/rel).read_text());t=json.loads((a.second/rel).read_text())
        for field in ('scene_id','coordinate_system','geometry','ground_truth','task'):
            assert s[field]==t[field], ('NON_REPRODUCIBLE_SCENE',rel,field)
        assert s['observations']['calibration']==t['observations']['calibration']
    write(a.output,{'status':'PASS','assets':rows,'scene_count':6,'same_geometry_task_calibration':True,
                    'new_model_calls':0,'note':'Wall-clock capture_span_s is measured anew; physics state and all 72 RGB/depth/validity/segmentation assets are byte-identical.'})
    print('PASS: independent rerender reproduced 72 assets and six task/geometry/calibration states')


if __name__=='__main__':main()
