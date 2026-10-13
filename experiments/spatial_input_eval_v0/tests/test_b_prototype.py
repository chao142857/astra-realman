import sys,unittest,tempfile,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab/b_prototype'))
from estimate import backproject,obb,rectangles
from export_public import export,SCENES,sha
class BPrototypeTests(unittest.TestCase):
 def test_camera_axes(self):
  cal={'intrinsic':[[1,0,0],[0,1,0],[0,0,1]],'pose_base_xyz_wxyz':[1,2,3,1,0,0,0]}
  p=backproject(np.ones((2,2)),cal)
  np.testing.assert_allclose(p[0,0],[2,2,3]);np.testing.assert_allclose(p[1,1],[2,1,2])
 def test_rotated_target(self):
  theta=np.deg2rad(30);r=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
  points=np.array([[x,y,z] for x in [-.06,.06] for y in [-.025,.025] for z in [.1,.15]])
  points[:,:2]=points[:,:2]@r.T+[.4,.2];b=obb(points)
  np.testing.assert_allclose(b['center_m'],[.4,.2,.125],atol=1e-9);np.testing.assert_allclose(sorted(b['size_m']),[.05,.05,.12],atol=1e-9)
 def test_rectangles_preserve_slot(self):
  m=np.ones((8,8),bool);m[2:6,2:6]=False;got=np.zeros_like(m)
  for x,y,x1,y1 in rectangles(m):got[y:y1,x:x1]=True
  np.testing.assert_array_equal(got,m)
 def test_export_ignores_segmentation_and_private_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);suite=root/'suite'
   for scene in SCENES:
    src=suite/scene;model=src/'model_inputs/RGB_MULTI_VIEW';assets=src/'assets';model.mkdir(parents=True);assets.mkdir();rgb=model/'image-0.png';rgb.write_bytes(b'public-rgb')
    (model/'context.json').write_text(json.dumps({'geometry':None,'attachments':[{'camera_id':'front','file':'image-0.png','sha256':sha(rgb)}]}))
    np.savez(assets/'front_rgbd.npz',depth_m=np.ones((2,2)),valid=np.ones((2,2),bool),segmentation=np.array([{'PRIVATE':'DO NOT READ'}],object))
    (src/'snapshot.json').write_text('not even valid json: inaccessible private geometry')
   export(suite,root/'public');m=json.loads((root/'public/manifest.json').read_text());self.assertFalse(m['segmentation_used'])
   self.assertEqual(m['npz_members_read'],['depth_m','valid']);self.assertFalse(any('snapshot' in x['file'] or 'segmentation' in x['file'] for x in m['files']))
if __name__=='__main__':unittest.main()
