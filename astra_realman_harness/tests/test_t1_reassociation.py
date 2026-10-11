"""Archived sensor replay and explicit negative software cases; no physics/model."""
import copy,json,os,unittest
from pathlib import Path
from unittest.mock import patch
from platform_v1.research import rgbd_world as rw
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead

class ReassociationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('GEOMETRY_FIRST_ARCHIVE_ROOT'):raise unittest.SkipTest('sealed sensor inputs required')
        root=Path(os.environ['GEOMETRY_FIRST_ARCHIVE_ROOT']);old=root/'run-t1-closed-loop-20261010'
        read=lambda p:json.loads(p.read_text())
        cls.previous=read(old/'observations/rm65_0002.json');cls.current=read(old/'observations/rm65_0004.json')
        cls.old=read(old/'worlds/2_semantic.json')['state']['entities']['object_004']
        state=read(root/'run-t1-reassociation-20261010/offline/WORLD.json')['state'];cls.new=state['entities']['object_004']
        store=PublicStore(old/'episode/public',cls.previous['episode_id'])
        for o in (cls.previous,cls.current):store.observe(o,o['execution_epoch'])
        cls.head=WorldHead(None,store,epoch=lambda:1,deadline=float('inf'),emit=lambda *x:None)
        cls.cfg=read(Path('config/research/geometry_first_update_v1.json'));cls.tracker=state['object_config']['tracker']
    def match(self,olds=None,news=None):
        return rw.associate_geometry_frames(olds or {'old':self.old},news or {'new':self.new},self.previous,self.current,
            self.head._images(self.current['observation_id']),self.head._images,self.cfg,self.tracker)
    def test_real_expired_current_measurement_uniquely_matches(self):
        before=copy.deepcopy(self.old);matches,r=self.match();self.assertEqual(matches,{'old':'new'})
        self.assertEqual(r['pairs'][0]['mode'],'expired_reassociation');self.assertGreater(r['pairs'][0]['history_age_s'],30)
        self.assertEqual(self.old,before);self.assertNotEqual(self.new['point_world_m'],self.old['point_world_m'])
        self.assertEqual(self.new['observation_id'],self.current['observation_id'])
    def test_expired_competition_not_nearest(self):
        matches,r=self.match(news={'a':self.new,'b':copy.deepcopy(self.new)});self.assertEqual(matches,{})
        self.assertEqual(len(r['previous_candidates']['old']),2)
        matches,r=self.match(olds={'a':self.old,'b':copy.deepcopy(self.old)});self.assertEqual(matches,{})
    def test_expired_missing_current_visual_rejected(self):
        with patch.object(rw,'track_view',return_value={'mask':None,'reason':'SYNTHETIC_NO_SUPPORT','association':'unknown'}):
            matches,r=self.match()
        self.assertEqual(matches,{});self.assertIn('EXPIRED_CURRENT_RGB_TRACK_SUPPORT',r['pairs'][0]['rejection_reasons'])
    def test_expired_missing_multiview_rejected(self):
        new=copy.deepcopy(self.new);new['association_evidence']=[]
        matches,r=self.match(news={'new':new});self.assertEqual(matches,{})
        self.assertIn('EXPIRED_CURRENT_MULTIVIEW_MEASUREMENT',r['pairs'][0]['rejection_reasons'])
    def test_expired_shape_only_cannot_promote_old_location(self):
        import numpy as np
        new=copy.deepcopy(self.new);new['candidate_surface_cloud']=(np.array(new['candidate_surface_cloud'])+[.07,0,0]).tolist()
        matches,r=self.match(news={'new':new});self.assertEqual(matches,{})
        self.assertIn('EXPIRED_RAW_GEOMETRY_SUPPORT',r['pairs'][0]['rejection_reasons'])
