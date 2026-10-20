import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase2a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src')]
from aspire_realman_phase2a.model import build_model,synthetic_layout
p=argparse.ArgumentParser();p.add_argument('--source-urdf',type=Path,required=True);p.add_argument('--source-config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--sphere-group-size',type=int,default=1)
p.add_argument('--coincident-synthetic-bases',action='store_true',help='collision negative fixture only, NEVER physical calibration')
p.add_argument('--synthetic-finger-midpoints',action='store_true',help='URDF-valid synthetic configuration only; original collision pairs unchanged')
a=p.parse_args()
a.output.resolve().relative_to(ROOT)
layout=synthetic_layout()
if a.coincident_synthetic_bases:
    layout['base_transforms']['right']=layout['base_transforms']['left']
    layout['purpose']='DELIBERATE COINCIDENT ROBOTS COLLISION NEGATIVE FIXTURE ONLY'
m=build_model(a.source_urdf,a.source_config,a.output,layout=layout,sphere_group_size=a.sphere_group_size,synthetic_finger_midpoints=a.synthetic_finger_midpoints)
print(json.dumps({k:m[k] for k in ('model','scope','active_sphere_count_dual','sphere_group_size')}))
