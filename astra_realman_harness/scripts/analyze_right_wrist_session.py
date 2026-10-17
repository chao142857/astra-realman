"""Offline right-wrist audit; reuses existing hand-eye solver. No devices."""
import argparse,json,hashlib,sys
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parent))
from inspect_onsite_handeye import pnp,solve,residual,choose_corner_order,synthetic_check,angular_deg,rpy_rotation

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 a.output.mkdir(exist_ok=False)
 policy={'stationary_window_frames':3,'max_xyz_range_m':.002,'max_angle_deg':1.,'max_corner_shift_px':1.,'max_host_capture_to_robot_end_s':.5,'distinct_xyz_m':.01,'distinct_angle_deg':7.,'selection':'chronological first qualifying frame; reject near-duplicates against all previously selected poses','holdout':'every third selected pose (index%3==2), frozen before fitting','min_selected':9,'corner_symmetry':'fit order on train only; heldout 180-degree origin chosen by rotation consistency only','board_square_scale':'estimated on training robot translations; not assumed 15 mm','no_model_calls':True}
 write(a.output/'selection_policy.json',policy)
 selftest=synthetic_check();rows=[];excluded=[]
 for f in sorted((a.run/'observations').iterdir()):
  try:
   o=json.loads((f/'observation.json').read_text());c=json.loads((f/'board_corners.json').read_text())['wrist'];s=o['state']['canonical_states']['right'];d=next(x for x in o['depth'] if x['camera']=='wrist');rgb=next(x for x in o['rgb'] if x['camera']=='wrist')
   if c['status']!='CORNERS_FOUND':raise ValueError('NO_CORNERS')
   if rgb['role']!='right_wrist' or rgb['serial']!='348522072063':raise ValueError('WRIST_ID')
   if s['system_error']['has_error'] or not s['frame_snapshot_stable']:raise ValueError('ROBOT_STATE')
   for frame in ('work_frame','tool_frame'):
    if not np.allclose(s[frame]['pose']['xyz_m']+s[frame]['pose']['rpy_rad'],0,atol=1e-12):raise ValueError('NONZERO_FRAME')
   if s['work_frame']['name']!='World' or s['tool_frame']['name']!='Arm_Tip':raise ValueError('FRAME_NAME')
   if sha(f/'wrist.png')!=rgb['sha256'] or rgb['sha256']!=c['image_sha256']:raise ValueError('RGB_HASH')
   robot=json.loads((f/'robot_raw.json').read_text());dt=robot['host_monotonic_interval'][1]-d['captured_monotonic']
   if not 0<=dt<=.5:raise ValueError('HOST_TIME_GAP')
   k=d['color_intrinsics'];coeff=np.array(k['distortion_coefficients'])
   if np.any(coeff!=0):raise ValueError('DISTORTION_UNSUPPORTED')
   pts=np.array(c['corners_px']);r,t,err=pnp(pts,np.array(k['matrix']),coeff)
   rows.append({'index':int(f.name),'robot_R':rpy_rotation(s['ee_pose']['rpy_rad']),'robot_t':np.array(s['ee_pose']['xyz_m']), 'points':pts,'camera_options':[(r,t),(r@np.diag([-1.,-1.,1.]),t+r@np.array([10.,6.,0.]))], 'pnp_reprojection_rms_px':err,'host_gap_s':dt,'observation_sha256':sha(f/'observation.json'),'image_sha256':rgb['sha256']})
  except Exception as e:excluded.append({'index':f.name,'reason':str(e)})
 by={r['index']:r for r in rows};chosen=[];stationary=[]
 for row in rows:
  neigh=[by.get(row['index']+j) for j in [-1,0,1]]
  if any(n is None for n in neigh):continue
  if any(np.linalg.norm(n['robot_t']-row['robot_t'])>.002 or angular_deg(n['robot_R'],row['robot_R'])>1 for n in neigh):continue
  if any(min(np.max(np.linalg.norm(n['points']-row['points'],axis=1)),np.max(np.linalg.norm(n['points'][::-1]-row['points'],axis=1)))>1 for n in neigh):continue
  stationary.append(row['index'])
  if any(np.linalg.norm(row['robot_t']-old['robot_t'])<.01 and angular_deg(row['robot_R'],old['robot_R'])<7 for old in chosen):continue
  chosen.append(row)
 report={'run':str(a.run),'synthetic_solver_check':selftest,'raw_frames':len(list((a.run/'observations').iterdir())),'valid_corner_rows':len(rows),'stationary_indices':stationary,'selected_indices':[r['index'] for r in chosen],'excluded':excluded,'parent_frame':'right SDK-reported endpoint; zero World/Arm_Tip conditional binding, not physical pad TCP','transform_semantics':'T_endpoint_camera_optical; p_endpoint=T@p_camera; metres','source_sha256':sha(Path(__file__)),'solver_sha256':sha(Path(__file__).with_name('inspect_onsite_handeye.py'))}
 write(a.output/'selection.json',report)
 if len(chosen)<9:
  report={'status':'INSUFFICIENT_DISTINCT_STATIONARY_POSES','selected':len(chosen)};write(a.output/'result.json',report);print(json.dumps(report));return
 train=[r for i,r in enumerate(chosen) if i%3!=2];held=[r for i,r in enumerate(chosen) if i%3==2]
 flips=choose_corner_order(train);x,board,scale,rr,sing=solve(train,flips,list(range(len(train))))
 def stats(samples,flips):
  values=[dict(index=r['index'],**residual(r,fl,x,board,scale),corner_order=fl,pnp_rms_px=r['pnp_reprojection_rms_px'],host_gap_s=r['host_gap_s']) for r,fl in zip(samples,flips)]
  return {'rows':values,'translation_rms_mm':float(np.sqrt(np.mean([v['translation_mm']**2 for v in values]))),'rotation_rms_deg':float(np.sqrt(np.mean([v['rotation_deg']**2 for v in values]))),'translation_max_mm':max(v['translation_mm'] for v in values)}
 hf=[min((0,1),key=lambda f:residual(r,f,x,board,scale)['rotation_deg']) for r in held]
 result={'status':'ESTIMATED_WITH_HELDOUT_RESIDUALS_NOT_MOTION_CERTIFICATION','T_endpoint_camera_optical':x.tolist(),'T_right_reference_board':board.tolist(),'square_mm':scale*1000,'train':stats(train,flips),'heldout':stats(held,hf),'linear_singular_values':sing.tolist(),'linear_condition':float(sing[0]/sing[-1]),'selected_pose_count':len(chosen),'training_count':len(train),'holdout_count':len(held),'installation_fixed_by_user':True,'physical_pad_TCP':'NOT_MEASURED','left_right_base_transform':'NOT_SOLVED','external_absolute_accuracy':'NOT_MEASURED','motion_commands':0,'model_requests':0}
 write(a.output/'result.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('train','heldout')},ensure_ascii=False));print('TRAIN',json.dumps(result['train']));print('HELDOUT',json.dumps(result['heldout']))
if __name__=='__main__':main()
