"""Frozen REAL INPUT and explicit SYNTHETIC fault/output helpers; no dispatch."""
import copy,hashlib,json,os,shutil
from pathlib import Path
import numpy as np
from PIL import Image
from platform_v1.research.public_store import PublicStore
from platform_v1.research.semantic_binding import import_grounding_archive,restore_persistent_world

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def workspace():
    import unittest
    if not os.environ.get('GEOMETRY_FIRST_ARCHIVE_ROOT'):raise unittest.SkipTest('requires sealed archives for REAL INPUT replay')
    return Path(os.environ['GEOMETRY_FIRST_ARCHIVE_ROOT'])
def sealed_store(public=None):
    ws=workspace();a=ws/'semantic-grounding-authorized-01-20261010'
    cfg=read(ROOT/'config/research/persistent_semantic_s1_v1.json')
    o=read(a/'OBSERVATION.json');base=read(ws/'geometry-first-v2-20261010/results/geometry/WORLD.json')
    w=read(ws/'persistent-semantic-binding-20261010/result/WORLD.json')
    store=PublicStore(public or a/'public_rgb_only',o['episode_id']);store.observe(o,o['execution_epoch'])
    store.worlds[base['world_id']]=base;store.current_world_id=base['world_id'];store.revision=1;store.read_versions=base['read_versions']
    import_grounding_archive(store,a,cfg['archive_manifest_sha256'],base['world_id'],cfg['evidence_id'])
    restore_persistent_world(store,w,w['world_id'],cfg['task'])
    return store,o,w,cfg
def sensor_store(root):
    public=root/'public';shutil.copytree(workspace()/'semantic-s1-capture-20261009/public',public)
    return sealed_store(public)
def inject_observation(store,old,index,mode='unchanged'):
    """Synthetic new timestamp/metadata, copied or corrupted sensor arrays.

    These are fault injections, NOT newly captured physical observations. New
    hashes bind the actual injected pixels; the runtime provenance marks them.
    """
    o=copy.deepcopy(old);oid='SYNTHETIC_FAULT:%04d'%index;now=old['captured_monotonic']+1
    o.update(observation_id=oid,captured_monotonic=now,execution_epoch=old['execution_epoch']+1,
             research_input_provenance='SYNTHETIC_FAULT_INJECTION')
    o['state']['sim_step']+=1
    dest=store.root/('fault-%04d'%index);dest.mkdir()
    for rgb,meta in zip(o['rgb'],o['depth']):
        # Camera records are matched by name, not assumed list order.
        camera=rgb['camera'];meta=next(x for x in o['depth'] if x['camera']==camera)
        old_rgb=next(x for x in old['rgb'] if x['camera']==camera)
        old_meta=next(x for x in old['depth'] if x['camera']==camera)
        rgb_bytes=(store.root/old_rgb['file']).read_bytes();(dest/(camera+'.png')).write_bytes(rgb_bytes)
        rgb['file']=str((dest/(camera+'.png')).relative_to(store.root))
        rgb['sha256']=hashlib.sha256(rgb_bytes).hexdigest()
        directory=store.root/Path(old_rgb['file']).parent
        depth=np.load(directory/old_meta['depth']['file'],allow_pickle=False)
        valid=np.array(Image.open(directory/old_meta['validity']['file']))
        if mode=='holes' or (mode=='wrist_holes' and camera=='wrist'):depth[:]=0;valid[:]=0
        if mode=='occlusion':depth[valid>0]*=.5
        if mode=='nan':depth[0,0]=np.nan
        np.save(dest/(camera+'.depth.npy'),depth,allow_pickle=False)
        Image.fromarray(valid).save(dest/(camera+'.valid.png'))
        for key,suffix in (('depth','.depth.npy'),('validity','.valid.png')):
            p=dest/(camera+suffix);meta[key]={'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'relative_to':'matching_rgb_directory'}
        meta.update(frame_id=oid+'/'+camera,captured_monotonic=now,capture_interval_monotonic=[now-.01,now],
            readback_completed_monotonic=now+.01,sensor_timestamp=old_meta['sensor_timestamp']+.01,
            simulation_step=o['state']['sim_step'],aligned_rgb_sha256=rgb['sha256'])
    if mode=='bad_fk':o['state']['flange_pose_world'][0]+=.2
    store.observe(o,o['execution_epoch'])
    fb={'ok':True,'completed_monotonic':now-.02,'source_observation_id':old['observation_id'],
        'source':'SYNTHETIC_FAULT_INJECTION_NOT_PHYSICAL_COMPLETION'}
    return o,fb
