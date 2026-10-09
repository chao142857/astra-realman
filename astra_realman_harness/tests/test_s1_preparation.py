"""Input/authorization contracts only. No capture, model, GPU or owner launch."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from scripts import prepare_s1_capture as capture
from platform_v1.research.s1_input_audit import perception_bundle,coverage
from platform_v1.research.public_store import PublicStore

ARCHIVE=Path(__file__).resolve().parents[3]/'rgbd-world-20261009/inputs/D0_control'

class S1PreparationTests(unittest.TestCase):
    def test_default_is_read_only_and_no_actual_coverage_claim(self):
        with patch.object(capture.subprocess,'Popen',side_effect=AssertionError('no process')):
            m=capture.manifest()
        self.assertEqual(m['new_SAPIEN_episodes'],0);self.assertIn('UNKNOWN',m['pixel_coverage'])
    def test_denied_and_wrong_scope_never_authorize(self):
        a=capture.read(capture.DOC/'CAPTURE_AUTHORIZATION_TEMPLATE.json')
        for edit in (lambda x:None,lambda x:x.update(granted=True,scope='G1_ONLY'),lambda x:x.update(granted=True,max_owner_submissions=1)):
            b=copy.deepcopy(a);edit(b)
            with self.assertRaisesRegex(ValueError,'SEPARATE_EXPLICIT'):capture.validate_approval(b)
    def test_protocol_bound_approval_contract_only(self):
        # TEST RECORD, never used to start worker. Real file stays granted=false.
        a=capture.read(capture.DOC/'CAPTURE_AUTHORIZATION_TEMPLATE.json');a['granted']=True
        capture.validate_approval(a);a['protocol_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SEPARATE_EXPLICIT'):capture.validate_approval(a)
    def test_help_and_default_do_not_import_physics_or_model(self):
        code="import sys; from scripts.prepare_s1_capture import manifest; manifest(); assert not any(x in sys.modules for x in ('sapien','torch','platform_v1.owner','platform_v1.research.broker'))"
        subprocess.run([sys.executable,'-B','-c',code],check=True)
    def test_runtime_source_pins_checked_without_importing_runtime(self):
        assets=Path(__file__).resolve().parents[3]/'astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets'
        capture.verify_sources(assets)
        original=capture.sha
        with patch.object(capture,'sha',side_effect=lambda p:'0'*64 if str(p).endswith('owner.py') else original(p)):
            with self.assertRaisesRegex(ValueError,'CAPTURE_SOURCE_CHANGED'):capture.verify_sources(assets)
    def archived(self):
        o=capture.read(ARCHIVE/'observations.json')[0];s=PublicStore(ARCHIVE/'public',o['episode_id']);s.observe(o,o['execution_epoch'])
        masks=capture.read(ARCHIVE/'masks.json');a=capture.read(ARCHIVE/'annotation.json');entities=[]
        for e in a['result']['entities']:
            entities.append({'reference_id':e['entity_id'],'appearance':'red_cuboid' if e['kind']=='object' else 'other',
                'cross_view_reference_status':'diagnostic_only','views':[{'camera':m['camera'],'mask':m['mask'],'image_sha256':m['image_sha256']} for m in masks if m['entity_id']==e['entity_id']]})
        return s,o,{'version':'astra.s1_rgb_reference.v1','observation_id':o['observation_id'],
            'source':'INDEPENDENT_CURRENT_RGB_ANNOTATION_NOT_MODEL_INPUT','entities':entities}
    def test_archived_single_object_cannot_claim_s1_coverage(self):
        s,o,a=self.archived();r=coverage(s,o['observation_id'],a,{'normal':[0,0,1],'offset':0})
        self.assertEqual(r['status'],'DATA_INSUFFICIENT');self.assertFalse(r['grants_execution'])
        self.assertEqual(len(r['rows']),2)
        self.assertTrue(all(len(e['views'])==3 for e in r['rows']))
    def test_bad_annotation_hash_rejected(self):
        s,o,a=self.archived();a['entities'][0]['views'][0]['image_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'REFERENCE_RGB_HASH'):coverage(s,o['observation_id'],a,{'normal':[0,0,1],'offset':0})
    def test_e0_payload_excludes_depth_and_annotation(self):
        s,o,a=self.archived();b=perception_bundle(s,o['observation_id'],'test task only')
        self.assertNotIn('depth',b['observation']);self.assertNotIn('state',b['observation']);self.assertNotIn('entities',b)
        self.assertEqual(len(b['request']['images']),3);self.assertIsNone(b['request']['world_id']);self.assertEqual(b['model_calls'],0)

if __name__=='__main__':unittest.main(verbosity=2)
