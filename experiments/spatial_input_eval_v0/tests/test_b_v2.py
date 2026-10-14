"""Offline B v2 measurement semantics and frozen artifact contracts."""
import hashlib,importlib.util,json,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('b_v2_measurement',ROOT/'lab/b_v2/estimate.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class BV2Tests(unittest.TestCase):
 def test_sensor_pixel_centers(self):
  c={'intrinsic':[[2,0,1],[0,2,1],[0,0,1]],'pose_base_xyz_wxyz':[1,2,3,1,0,0,0]}
  np.testing.assert_allclose(m.points(np.ones((2,2)),c)[0,0],[2,2.25,3.25])
 def test_ray_free_surface_occluded_and_unseen(self):
  cal={'intrinsic':[[100,0,1.5],[0,100,1.5],[0,0,1]],'pose_base_xyz_wxyz':[0,0,0,1,0,0,0]}
  camera={'depth':np.ones((3,3)),'valid':np.ones((3,3),bool),'cal':cal}
  self.assertEqual(m.ray_states(np.array([[.5,0,0],[1,0,0],[1.5,0,0],[-1,0,0],[1,10,0]]),[camera]).tolist(),[0,1,2,2,2])
 def test_missing_bottom_is_explicit_not_global_floor(self):
  p=[];n=[]
  for axis in range(3):
   for sign in (-1,1):
    if axis==2 and sign==-1:continue
    for a in np.linspace(-.018,.018,8):
     for b in np.linspace(-.018,.018,8):
      q=[a,b,0.];other=[i for i in range(3) if i!=axis];q[axis]=sign*.02;q[other[0]]=a;q[other[1]]=b;q[2]+=.2;p.append(q);normal=[0.,0.,0.];normal[axis]=sign;n.append(normal)
  box,info,_=m.target_box(np.array(p),np.array(n),np.zeros(len(p),int),np.full(len(p),.001))
  self.assertTrue(any(x['axis']==2 and x['side']==-1 for x in info['missing_faces']))
  self.assertGreater(box['center_m'][2]-box['size_m'][2]/2,.18)
 def test_frozen_sources_and_all_estimate_hashes(self):
  e=ROOT/'evidence/b_v2_20261014'
  for name,digest in json.loads((e/'pre_estimation_lock.json').read_text())['source_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
  for name in ('validation_B1','validation_B2','development_B2'):
   f=e/name;freeze=json.loads((f/'freeze.json').read_text())
   for item in freeze['files']:self.assertEqual(hashlib.sha256((f/item['file']).read_bytes()).hexdigest(),item['sha256'])
 def test_public_context_preserved_and_unknown_explicit(self):
  e=ROOT/'evidence/b_v2_20261014'
  for scene in sorted((e/'public_validation').iterdir()):
   if not scene.is_dir():continue
   public=json.loads((scene/'context.json').read_text())
   for version in ('validation_B1','validation_B2'):
    folder=e/version/scene.name;context=json.loads((folder/'context.json').read_text());context['geometry']=None;self.assertEqual(context,public)
    for i in range(3):self.assertEqual((folder/f'image-{i}.png').read_bytes(),(scene/f'image-{i}.png').read_bytes())
   reliability=json.loads((e/'validation_B2'/scene.name/'reliability.json').read_text());self.assertFalse(reliability['segmentation_used'])
   for obj in reliability['objects']:
    if obj['id']!='target':self.assertIn('UNKNOWN',obj['bottom_status']);self.assertEqual(obj['ray_probe_states']['free'],0)
 def test_isolated_reads_are_only_manifest_public_rgb_depth(self):
  e=ROOT/'evidence/b_v2_20261014'
  for name in ('validation_B1','validation_B2','development_B2'):
   audit=json.loads((e/name/'isolation_audit.json').read_text());self.assertEqual(audit['status'],'PASS');self.assertTrue(audit['network_and_process_launch_denied'])
   for path in audit['public_files_opened']:self.assertNotIn('snapshot',path);self.assertNotIn('segmentation',path);self.assertNotIn('private',path)
if __name__=='__main__':unittest.main()
