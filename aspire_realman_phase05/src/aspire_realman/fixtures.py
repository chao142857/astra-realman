"""Clearly labelled synthetic CPU data; never substitute these transforms for hardware."""
from __future__ import annotations
import time
import numpy as np
from cap_harness.contracts import Segmentation, SegmentationSet
from .codec import CodecConfig, EndpointBinding, TransformEdge
from .sources import MemorySource


def synthetic_station():
    now = time.time(); states = {}; bindings = {}; edges = []
    for arm, translation in [('left', [0.2,-0.1,0.5]), ('right', [-0.4,0.3,0.2])]:
        work = f'synthetic:{arm}:work'; tool = f'synthetic:{arm}:Arm_Tip'
        states[arm] = {'arm': arm, 'joint_deg': [0,10,20,30,40,50], 'joint_velocity_deg_s': [1,2,3,4,5,6],
            'ee_pose': {'xyz_m': [0.1,0.2,0.3], 'rpy_rad': [0,0,np.pi/2], 'units': {'xyz':'m','rpy':'rad'}, 'frame_semantics_status':'SYNTHETIC'},
            'work_frame': {'id':work, 'definition_fingerprint':f'synthetic-{arm}-work'},
            'tool_frame': {'id':tool, 'definition_fingerprint':f'synthetic-{arm}-tool'},
            'frame_snapshot_stable': True, 'timestamp': now, 'gripper_state': {'position':500}}
        bindings[arm] = EndpointBinding(arm, work, tool, f'synthetic-{arm}-work', f'synthetic-{arm}-tool', 'SYNTHETIC_FIXTURE', True)
        t = np.eye(4); t[:3,3] = translation
        edges.append(TransformEdge('synthetic:work', work, t, 'SYNTHETIC', 'SYNTHETIC_FIXTURE_NOT_HARDWARE'))
    rgb = np.zeros((12,16,3), dtype=np.uint8); rgb[:,:,1] = 180
    yy, xx = np.mgrid[:12,:16]
    depth = 0.6 + 0.005*xx + 0.002*yy + 0.0005*xx*yy
    t = np.eye(4); t[:3,3] = [0.13,-0.21,0.44]
    camera = {'role':'synthetic_overhead','serial':'SYNTHETIC-ONLY','rgb':rgb, 'depth_m':depth,
        'intrinsics':[[100,0,7.5],[0,100,5.5],[0,0,1]], 'captured_at':now,
        'optical_frame':'synthetic:camera_optical','parent_frame':'synthetic:work',
        'T_parent_camera_optical':t, 'calibration_status':'SYNTHETIC','geometry_eligible':True}
    snapshot = {'mode':'SYNTHETIC','canonical_states':states,'cameras':[camera], 'captured_at':now,'sequence':1,
                'provenance':{'kind':'SYNTHETIC; no real calibration or robot data'}}
    return MemorySource(snapshot), CodecConfig(('left','right'),'synthetic:work',bindings,tuple(edges))


class MockSegmentation:
    """Deterministic generic mask provider for wire/geometry tests, no task policy."""
    def segment_text(self, camera, text):
        mask = np.zeros(camera.rgb.shape[:2], dtype=bool); mask[2:-2,2:-2] = True
        return SegmentationSet(ok=True, segmentations=[Segmentation(mask=mask,label=text,score=1,
            camera_name=camera.frame,frame=camera.frame)])
