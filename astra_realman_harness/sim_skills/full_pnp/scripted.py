"""PRIVATE engineering script. Deliberate GT use; never imported by wire/worker/policy."""
import json
from pathlib import Path


def engineering_script(backend,run):
    s=backend.s;x,y=s.object_pose()[:2];gx,gy=s.cfg['scene']['place_zone_xy']
    pose=lambda xyz:{'type':'move_pose','pose':[*map(float,xyz),0,1,0,0]}
    plan=[{'actions':[pose([x,y,.18]),pose([x,y,.08]),pose([x,y,.04])]},
          {'actions':[{'type':'gripper','opening':.45}]},
          {'relative_lift_after_closure':.08},
          {'actions':[pose([gx,gy,.12])]}, {'actions':[pose([gx,gy,.04])]},
          {'actions':[{'type':'gripper','opening':1.}]}, {'actions':[pose([gx,gy,.12])]}]
    (Path(run)/'PRIVATE_ENGINEERING_ANSWERS.json').write_text(json.dumps({'source':'GT_SCRIPT_NOT_ASTRA_NOT_B_F','plan':plan},indent=2))
    return plan
