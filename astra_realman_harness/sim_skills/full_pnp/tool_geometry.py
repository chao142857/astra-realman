"""Robot-only tool geometry for model context; no scene/control/target access."""
import hashlib,json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

VERSION='ctag.contact_geometry_context.v1'
CALIBRATION=Path(__file__).resolve().parents[2]/'config/research/ctag_contact_geometry_v1.json'
CALIBRATION_SHA256='3a32b2cb51e5e249f4cb3f8126abe3ca93cc0d36cfefb31f1b03a96ba742033a'


def fk(model, joint_values):
    """URDF joint transforms relative to Link6. Uses measured joints when supplied."""
    poses={'Link6':np.eye(4)};pending=list(model['joints']);values=dict(joint_values)
    while pending:
        progress=False
        for j in pending[:]:
            if j['parent'] not in poses:continue
            q=0.
            if j['type']!='fixed':
                if j['name'] not in values:
                    m=j['mimic'];values[j['name']]=values[m['joint']]*m['multiplier']+m['offset']
                q=values[j['name']]
            motion=np.eye(4);motion[:3,:3]=Rotation.from_rotvec(np.asarray(j['axis'])*q).as_matrix()
            poses[j['child']]=poses[j['parent']]@np.asarray(j['origin'])@motion
            pending.remove(j);progress=True
        if not progress:raise ValueError('TOOL_KINEMATIC_CHAIN')
    return poses


def surfaces(model, values):
    poses=fk(model,values);pads=[];hulls=[]
    for link in model['supports']:
        t=poses[link['link']]
        pads.append(np.asarray(link['pad_vertices'])@t[:3,:3].T+t[:3,3])
        hulls.append(np.asarray(link['collision_hull_vertices'])@t[:3,:3].T+t[:3,3])
    return pads,hulls


def load_calibration():
    data=CALIBRATION.read_bytes()
    if hashlib.sha256(data).hexdigest()!=CALIBRATION_SHA256:raise ValueError('TOOL_CALIBRATION_HASH')
    return json.loads(data)


def context(observation):
    """Nominal closure shapes and measured FK only; never a grasp waypoint."""
    model=load_calibration();s=observation['state']
    q=dict(zip(s['joint_names'],s['qpos'],strict=True))
    for j in model['joints']:
        if j['type']!='fixed' and j['name'] not in q:raise ValueError('TOOL_MEASURED_JOINT_MISSING')
    flange=np.asarray(s['flange_pose_world'],float);measured=np.asarray(s['actual_grasp_center_world'],float)
    if not np.isfinite([*q.values(),*flange,*measured]).all():raise ValueError('TOOL_NONFINITE_STATE')
    R=Rotation.from_quat(np.roll(flange[3:],-1)).as_matrix()
    measured_local=R.T@(measured-flange[:3])
    current_pads,_=surfaces(model,q)
    current_centers=np.array([v.mean(0) for v in current_pads]);center=current_centers.mean(0)
    samples=[];shapes=None
    for master in model['nominal_master_samples_rad']:
        pads,hulls=surfaces(model,{model['master_joint']:master})
        centers=np.array([v.mean(0) for v in pads]);mid=centers.mean(0)
        # Ideal mimic keeps each support orientation fixed over closure. Describe
        # its shape once, translating by the separate left/right pad samples.
        # Coordinates are offsets from CURRENT measured pad center, no target XYZ.
        relative_pads=[(v-c)@R.T for v,c in zip(pads,centers)]
        relative_hulls=[(v-c)@R.T for v,c in zip(hulls,centers)]
        shape=[{'side':side,'pad_bounds_m':np.round([v.min(0),v.max(0)],7).tolist(),
                'full_support_bounds_m':np.round([h.min(0),h.max(0)],7).tolist()}
               for side,v,h in zip(('left','right'),relative_pads,relative_hulls)]
        if shapes is None:shapes=shape
        elif shape!=shapes:raise ValueError('TOOL_NONPARALLEL_NOMINAL_SUPPORT')
        samples.append({'master_rad':master,'nominal_gap_m':round(float(np.linalg.norm(centers[0]-centers[1])),7),
          'pad_center_delta_world_m':np.round(R@(mid-measured_local),7).tolist(),
          'left_right_pad_center_deltas_world_m':np.round((centers-measured_local)@R.T,7).tolist()})
    return {'version':VERSION,'calibration_sha256':CALIBRATION_SHA256,'source_type':'ROBOT_URDF_COLLISION_MESH_AND_CURRENT_MEASURED_FK_NOT_OBJECT_TRUTH',
      'observation_id':observation['observation_id'],'units':'metres and radians; flange quaternion wxyz',
      'current_master_rad':s['gripper_master_rad'],'current_gap_m':s['actual_pad_gap_m'],
      'measured_pad_offset_flange_m':np.round(measured_local,7).tolist(),
      'URDF_measured_joints_vs_measured_pad_center_residual_m':float(np.linalg.norm(center-measured_local)),
      'closure_samples':samples,'shape_offsets_world_axes_relative_each_pad_center':shapes,
      'shape_use':'Translate each left/right shape by its corresponding sample pad-center delta. Ideal mimic only; not measured contact or swept-volume certification.',
      'constraints':model['constraints'],
      'source_hashes':model['source_hashes'],'grants_execution':False}
