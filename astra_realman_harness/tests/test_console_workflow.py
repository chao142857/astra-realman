import io
import json
import shlex
import shutil
import sys
import threading
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra_gui import CameraHub
from camera_session import CameraSession
from io_utils import ROOT
from launch_provenance import equivalent_command, snapshot, LaunchRecorder

class WorkflowTests(unittest.TestCase):
    def test_verbatim_command_and_manifest(self):
        task='  中文 "quoted" $(never-run)\nnext line  '
        settings={'task':task,'profile':'H5D1'}
        args=shlex.split(equivalent_command(settings))
        self.assertEqual(args[args.index('--task')+1],task)
        record=snapshot(settings,['python','run'])
        self.assertEqual(record['settings']['task'],task)
        self.assertEqual(record['actual_argv'],['python','run'])
        self.assertNotIn('token',record)
        folder=ROOT/'logs'/('workflow-'+uuid.uuid4().hex);folder.mkdir()
        self.addCleanup(shutil.rmtree,folder)
        out=io.StringIO();tee=LaunchRecorder(out,record)
        line='RUN → '+json.dumps({'log':str(folder)})+'\n'
        for chunk in (line[:5],line[5:]):tee.write(chunk)
        self.assertEqual(out.getvalue(),line)
        self.assertEqual(json.loads((folder/'launch_manifest.json').read_text()),record)
    def test_preview_never_consumes_snapshot_and_encoding_outside_lock(self):
        configs=[{'serial':'x','role':'fixed'}]
        session=CameraSession(configs)
        session.latest['x']={'shape':[1,1,3],'_pixels':b'abc','_stride':3,'host_received_monotonic':time.monotonic()}
        hub=CameraHub(configs);hub.session=session
        with patch.object(session,'snapshot',side_effect=AssertionError('preview consumed snapshot')):
            for _ in range(10):self.assertTrue(hub.image(0)[0])
        self.assertEqual(session.last_sequence,{})
        self.assertEqual(session.snapshot_count,0)
    def test_preview_on_off_preserves_frame_age_span_and_capture_wait(self):
        configs=[{'serial':str(i),'role':'view'+str(i)} for i in range(4)]
        records=[]
        with tempfile.TemporaryDirectory(dir=ROOT/'logs') as folder,patch('camera_session.time.monotonic',return_value=1000),patch('observation.png_rgb',return_value='mock-png-hash'):
            for preview in (False,True):
                session=CameraSession(configs);hub=CameraHub(configs);hub.session=session
                for i,c in enumerate(configs):
                    session.latest[c['serial']]={'serial':c['serial'],'sequence':10,'host_received_monotonic':999.99,
                        'host_received_at':500+i*.001,'device_timestamp_ms':(500+i*.001)*1000,
                        'device_timestamp_domain':'timestamp_domain.system_time','shape':[1,1,3],'_pixels':b'abc','_stride':3}
                if preview:
                    for _ in range(5):
                        for i in range(4):hub.image(i)
                self.assertEqual(session.snapshot_count,0);self.assertEqual(session.last_sequence,{})
                with patch.object(session.condition,'wait',side_effect=AssertionError('preview consumed freshness')):
                    started=time.perf_counter();images,failures,metrics=session.snapshot(Path(folder),configs=configs[:3]);elapsed=time.perf_counter()-started
                self.assertFalse(failures);self.assertLess(elapsed,1)
                records.append({'age_ms':[round((1000-i['host_received_monotonic'])*1000,6) for i in images],
                                'span_ms':round(metrics['capture_span_ms'],6),'capture_latency_s':round(elapsed,6)})
        self.assertEqual(records[0]['age_ms'],records[1]['age_ms']);self.assertEqual(records[0]['span_ms'],records[1]['span_ms'])
        print('SYNTHETIC_PREVIEW_COMPARISON '+json.dumps(records))
    def test_optional_fourth_does_not_wait_enumeration(self):
        from types import SimpleNamespace
        configs=[{'serial':str(i)} for i in range(4)]
        session=CameraSession(configs,rs_module=SimpleNamespace(camera_info=SimpleNamespace(serial_number='serial')),required_serials=['0','1','2'])
        ctx=SimpleNamespace(query_devices=lambda:[SimpleNamespace(get_info=lambda field,i=i:str(i)) for i in range(3)])
        with patch.object(session.stop_event,'wait',side_effect=AssertionError('optional camera caused wait')):
            self.assertEqual(session._enumerate_expected(ctx),{'0','1','2'})

if __name__=='__main__':unittest.main()
