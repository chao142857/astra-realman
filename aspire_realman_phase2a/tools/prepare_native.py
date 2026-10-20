"""Apply exact model-only changes to a copied/pinned ASPIRE provider service."""
import argparse,difflib,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--aspire-source',type=Path,default=ROOT/'.cache/ASPIRE');a=p.parse_args()
a.aspire_source.resolve().relative_to(ROOT)
path=a.aspire_source/'src/cap_harness/providers/curobo/service.py'
s=path.read_text();original=s
if 'ASPIRE_PHASE2A_REALMAN_REGISTRATION' in s:raise SystemExit('Already patched; use copied original service')
if hashlib.sha256(original.encode()).hexdigest()!='7a6f5747e74565f9646c60a0122d37121f5bf9cd5c40529d1a0af16d6377563f':
    raise SystemExit('PINNED_FA00F0E_PROVIDER_HASH_REQUIRED')
s=s.replace('from .dual import build_dual_panda_config','from .dual import build_dual_panda_config\n# ASPIRE_PHASE2A_REALMAN_REGISTRATION: model/service only, Agent untouched\nfrom aspire_realman_phase2a import provider as rm65')
s=s.replace('Literal["panda", "dual_panda", "yam_real"]','Literal["panda", "dual_panda", "yam_real", "realman_rm65_dual"]')
s=s.replace('    return override is not None and override != "0"','    if model == rm65.MODEL and override not in (None, "0"):\n        raise HTTPException(400, "RM65_COLLISION_DISABLING_FORBIDDEN")\n    return override is not None and override != "0"')
s=s.replace('def _robot_config(request: BaseRequest) -> str:\n','def _robot_config(request: BaseRequest) -> str:\n    if request.model == rm65.MODEL:\n        return rm65.config_for(request)\n')
s=s.replace('    arms = tuple(request.joint_positions)\n','    arms = tuple(request.joint_positions)\n    if request.model == rm65.MODEL:\n        rm65.validate_request(request)\n',1)
s=s.replace('JOINT_DIMENSIONS["yam_real" if request.model == "yam_real" else "robosuite"]','JOINT_DIMENSIONS["realman" if request.model == rm65.MODEL else "yam_real" if request.model == "yam_real" else "robosuite"]')
s=s.replace('    positions = _clip_joint_positions(positions[reorder], planner)','    positions = rm65.ordered_state(request, expected) if request.model == rm65.MODEL else _clip_joint_positions(positions[reorder], planner)')
s=s.replace('    if set(names) != set(expected):','    if request.model == rm65.MODEL:\n        names = expected\n        positions = rm65.ordered_state(request, expected)\n    if set(names) != set(expected):',1)
s=s.replace('    clipped = _clip_joint_positions(\n        positions.detach().cpu().numpy().reshape(-1),\n        planner,\n    )','    clipped = positions.detach().cpu().numpy().reshape(-1) if request.model == rm65.MODEL else _clip_joint_positions(\n        positions.detach().cpu().numpy().reshape(-1),\n        planner,\n    )')
# Install route before main(), after all native functions are defined.
marker='if __name__ == "__main__":'
assert marker in s
s=s.replace(marker,'import sys as _sys\nrm65.install_validation_routes(_sys.modules[__name__])\n\n\n'+marker)
path.write_text(s)
patch=''.join(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='a/src/cap_harness/providers/curobo/service.py',tofile='b/src/cap_harness/providers/curobo/service.py'))
(ROOT/'aspire_realman_phase2a/patches/0001-realman-curobo-model.patch').write_text(patch)
print(json.dumps({'provider_source':str(path),'before_sha256':hashlib.sha256(original.encode()).hexdigest(),'after_sha256':hashlib.sha256(s.encode()).hexdigest(),'patch_lines':len(patch.splitlines())}))
