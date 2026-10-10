import copy,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from candidate_update_fixtures import sensor_store,inject_observation
from platform_v1.research.world_head import WorldHead
from platform_v1.research.semantic_binding import validate_geometry_update
from platform_v1.research.verification_cache import Registry,canonical

class RegistryTests(unittest.TestCase):
    def test_nested_mutators_invalidate_tokens(self):
        edits=[lambda x:x['a'].append(3),lambda x:x['a'].__setitem__(0,4),lambda x:x['a'].__setitem__(slice(0,1),[6]),
               lambda x:x['a'].extend([2]),lambda x:x['a'].reverse(),lambda x:x['a'].sort(),lambda x:x['a'].pop(),
               lambda x:x['a'].insert(0,5),lambda x:x['a'].remove(1),lambda x:x['a'].__iadd__([3]),
               lambda x:x['a'].__imul__(2),lambda x:x['a'].clear(),lambda x:x['d'].update(z=1),
               lambda x:x['d'].setdefault('z',0),lambda x:x['d'].pop('v'),lambda x:x['d'].popitem(),lambda x:x['d'].clear(),
               lambda x:x['d'].__ior__({'z':2}),lambda x:x.__delitem__('d')]
        for edit in edits:
            r=Registry({'key':{'a':[1,2],'d':{'v':0}}});token=r.tokens['key'];edit(r['key']);self.assertIsNot(token,r.tokens['key'])
    def test_new_entries_and_external_alias_cannot_modify_pinned_entry(self):
        original={'a':[1]};r=Registry({'k':original});token=r.tokens['k'];r['new']={};original['a'].append(3)
        self.assertIs(token,r.tokens['k']);self.assertEqual(r['k'],{'a':[1]})

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store,self.o,self.w,self.cfg=sensor_store(self.root);self.epoch=0
        self.head=WorldHead(self.root/'head',self.store,epoch=lambda:self.epoch,deadline=time.monotonic()+240,emit=lambda *a:None)
    def tearDown(self):self.temp.cleanup()
    def update(self,index=1,old=None,reference=None):
        o,f=inject_observation(self.store,old or self.o,index);self.epoch=o['execution_epoch']
        w=self.head.update((reference or self.w)['world_id'],o['observation_id'],f['completed_monotonic'],execution_feedback=f)
        return o,w
    def test_cached_proof_is_immutable_and_full_audit_remains_real_reads(self):
        o,w=self.update();c=self.store.verification_cache;c.reset_metrics()
        validate_geometry_update(self.store,w);self.assertEqual(c.metrics['proof_hits'],1);self.assertEqual(c.metrics['file_reads'],0)
        proof=c.proofs[w['world_id']];self.assertIsInstance(proof.world_bytes,bytes)
        with self.assertRaises(Exception):proof.world_bytes=b'forged'
        c.reset_metrics();validate_geometry_update(self.store,w,full_audit=True)
        self.assertGreaterEqual(c.metrics['file_reads'],9);self.assertEqual(c.metrics['proof_hits'],0)
    def test_ancestor_nested_mutation_cannot_hide_behind_world_id(self):
        o,w=self.update();o2,w2=self.update(2,o,w)
        self.store.observations[o['observation_id']]['state']['qpos'][0]+=.1
        with self.assertRaisesRegex(ValueError,'OBSERVATION_CHANGED'):validate_geometry_update(self.store,w2)
    def test_current_registry_mutation_rejected_even_when_caller_holds_old_copy(self):
        o,w=self.update()
        self.store.worlds[w['world_id']]['state']['execution_feedback']['ok']=False
        with self.assertRaisesRegex(ValueError,'PUBLISHED_WORLD_MISMATCH'):validate_geometry_update(self.store,w)
    def test_ancestor_world_and_receipt_mutation_rejected(self):
        o,w=self.update();o2,w2=self.update(2,o,w)
        self.store.geometry_update_receipts[w['world_id']]['read_versions']['forged']=1
        with self.assertRaisesRegex(ValueError,'READ_VERSIONS'):validate_geometry_update(self.store,w2)
    def test_semantic_evidence_ancestor_mutation_rejected(self):
        o,w=self.update();eid=self.cfg['evidence_id'];self.store.evidence[eid]['result']['unknowns'].append('forged')
        with self.assertRaisesRegex(ValueError,'HASH|MISMATCH'):validate_geometry_update(self.store,w)
    def test_replacing_registry_is_not_token_equivalent(self):
        o,w=self.update();c=self.store.verification_cache;c.reset_metrics()
        self.store.observations=copy.deepcopy(dict(self.store.observations))
        validate_geometry_update(self.store,w);self.assertGreater(c.metrics['proof_misses'],0)
    def test_ancestor_depth_tamper_same_size_and_restored_mtime(self):
        o,w=self.update();o2,w2=self.update(2,o,w)
        rgb=o['rgb'][0];path=self.store.root/Path(rgb['file']).parent/(rgb['camera']+'.depth.npy')
        stamp=path.stat();data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'DEPTH_HASH'):validate_geometry_update(self.store,w2)
    def test_ancestor_rgb_symlink_substitution_rejected(self):
        o,w=self.update();p=self.store.root/o['rgb'][0]['file'];original=p.read_bytes();p.unlink()
        bad=self.root/'bad.png';bad.write_bytes(original+b'bad');p.symlink_to(bad)
        with self.assertRaisesRegex(ValueError,'PATH_ESCAPE|RGB_HASH'):validate_geometry_update(self.store,w)
    def test_mid_compute_source_mutation_rejected_before_publication(self):
        from platform_v1.research import rgbd_world
        original=rgbd_world.update_geometry_first
        def corrupt(*args,**kwargs):
            result=original(*args,**kwargs)
            current=args[2];self.store.observations[current['observation_id']]['state']['qpos'][0]+=.1
            return result
        with patch.object(rgbd_world,'update_geometry_first',side_effect=corrupt):
            with self.assertRaisesRegex(ValueError,'BEFORE_PUBLICATION'):self.update()
        self.assertEqual(self.store.revision,2)
    def test_current_observation_never_reuses_previous_transaction_validation(self):
        o,w=self.update();c=self.store.verification_cache;c.reset_metrics()
        with c.transaction(o['observation_id']):
            self.store.depth(o['observation_id'],'fixed');reads=c.metrics['file_reads']
            d,v,_=self.store.depth(o['observation_id'],'fixed');self.assertEqual(c.metrics['file_reads'],reads)
            with self.assertRaises(ValueError):d.setflags(write=True)
            with self.assertRaises(ValueError):v.setflags(write=True)
        with c.transaction(o['observation_id']):self.store.depth(o['observation_id'],'fixed')
        self.assertGreater(c.metrics['file_reads'],reads)
        with self.assertRaisesRegex(ValueError,'STALE_UPDATE_BASE'):
            self.head.update(self.w['world_id'],o['observation_id'],o['captured_monotonic']-.02)
        self.assertNotIn('estimation_compute_s',self.store.last_update_profile)
    def test_stale_current_versions_and_epoch_binding_still_rejected(self):
        o,w=self.update();self.store.read_versions['forged']=1
        with self.assertRaisesRegex(ValueError,'STALE'):validate_geometry_update(self.store,w)
        self.store.read_versions=copy.deepcopy(w['read_versions']);bad=copy.deepcopy(w);bad['binding']['execution_epoch']+=1
        with self.assertRaisesRegex(ValueError,'HASH'):validate_geometry_update(self.store,bad)

if __name__=='__main__':unittest.main(verbosity=2)
