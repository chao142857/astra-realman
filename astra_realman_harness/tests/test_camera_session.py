"""Offline regression tests for transient RealSense SDK enumeration."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from camera_session import CameraSession
from io_utils import ROOT

class Clock:
    def __init__(self): self.now=0.;self.waits=[]
    def monotonic(self): return self.now
    def time(self): return 1000.+self.now
    def wait(self,seconds):
        self.waits.append(seconds);self.now+=seconds
        return False

class ImmediateThread:
    def __init__(self,target,args,**kwargs): self.target=target;self.args=args
    def start(self): self.target(*self.args)
    def join(self,*args): pass

class EnumerationTests(unittest.TestCase):
    def rs(self,enumerations):
        calls={"contexts":0,"queries":0,"producer_contexts":[]}
        class Device:
            def __init__(self,serial): self.serial=serial
            def get_info(self,kind): return self.serial
        def query():
            index=min(calls["queries"],len(enumerations)-1)
            calls["queries"]+=1
            values=enumerations[index]
            if isinstance(values,Exception): raise values
            return [Device(s) for s in values]
        context=NS(query_devices=query)
        def make_context():
            calls["contexts"]+=1
            return context
        return NS(context=make_context,camera_info=NS(serial_number="serial")),context,calls

    def ready_producer(self,clock,calls):
        def produce(session,config,context):
            serial=config["serial"]
            calls["producer_contexts"].append(context)
            session.starts[serial]=session.starts.get(serial,0)+1
            session.latest[serial]={
                "serial":serial,"sequence":5,"host_received_monotonic":clock.now,
                "host_received_at":clock.time(),"device_timestamp_ms":clock.time()*1000,
                "device_timestamp_domain":"timestamp_domain.global_time",
                "shape":[1,1,3],"_pixels":b"abc","_stride":3}
        return produce

    def test_partial_enumeration_recovers_before_any_pipeline_starts(self):
        rs,context,calls=self.rs([["0"],["0","1","2","3"]])
        clock=Clock()
        configs=[{"serial":str(i)} for i in range(4)]
        session=CameraSession(configs,rs_module=rs,startup_timeout=.5)
        def produce(session_,config,context_):
            self.assertEqual(calls["queries"],2)
            self.ready_producer(clock,calls)(session_,config,context_)
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with patch("camera_session.time",clock), \
                 patch("camera_session.threading.Thread",ImmediateThread), \
                 patch.object(session.stop_event,"wait",side_effect=clock.wait), \
                 patch.object(CameraSession,"_produce",produce), \
                 patch("observation.png_rgb",return_value="test-image-hash"):
                with session:
                    images,failures,metrics=session.snapshot(Path(d))
                self.assertEqual(len(images),4)
                self.assertEqual(failures,[])
                self.assertEqual(metrics["pipeline_start_count"],{str(i):1 for i in range(4)})
                diagnostic=metrics["device_enumeration"]
                self.assertTrue(diagnostic["complete"])
                self.assertEqual([a["serials"] for a in diagnostic["attempts"]],
                                 [["0"],["0","1","2","3"]])
                self.assertEqual(diagnostic["attempts"][0]["missing_serials"],["1","2","3"])
                self.assertTrue(all("started_at" in a and "finished_at" in a for a in diagnostic["attempts"]))
                self.assertEqual(diagnostic["elapsed_s"],.2)
                self.assertEqual(metrics["startup_wait_budget_s"],1.)
                session.enumeration["attempts"][0]["serials"].append("later-mutation")
                self.assertEqual(diagnostic["attempts"][0]["serials"],["0"])
        self.assertEqual(calls["contexts"],1)
        self.assertEqual(calls["producer_contexts"],[context]*4)

    def test_permanently_missing_serial_has_bounded_retry_and_real_error(self):
        rs,context,calls=self.rs([[]])
        clock=Clock()
        session=CameraSession([{"serial":"missing"}],rs_module=rs,startup_timeout=.5)
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with patch("camera_session.time",clock), \
                 patch.object(session.stop_event,"wait",side_effect=clock.wait), \
                 patch.object(CameraSession,"_produce",side_effect=AssertionError("NO_PIPELINE")):
                with session:
                    images,failures,metrics=session.snapshot(Path(d))
        self.assertEqual(images,[])
        self.assertEqual(failures,[{"device":"missing","message":"SDK_SERIAL_NOT_FOUND"}])
        self.assertEqual(clock.now,.5)
        self.assertEqual(calls["queries"],4)
        self.assertEqual(calls["contexts"],1)
        self.assertTrue(all(0 < wait <= .2 for wait in clock.waits))
        self.assertFalse(metrics["device_enumeration"]["complete"])
        self.assertEqual(metrics["device_enumeration"]["missing_serials"],["missing"])
        self.assertEqual(metrics["pipeline_start_count"],{})
        self.assertEqual(metrics["frame_warmup"]["elapsed_s"],0.)

    def test_enumeration_exception_is_logged_then_read_only_retry_recovers(self):
        rs,context,calls=self.rs([RuntimeError("transient enumeration"),["0"]])
        clock=Clock()
        session=CameraSession([{"serial":"0"}],rs_module=rs,startup_timeout=.5)
        with patch("camera_session.time",clock), \
             patch("camera_session.threading.Thread",ImmediateThread), \
             patch.object(session.stop_event,"wait",side_effect=clock.wait), \
             patch.object(CameraSession,"_produce",self.ready_producer(clock,calls)):
            with session: pass
        self.assertEqual(session.enumeration["attempts"][0]["error"],
                         "RuntimeError:transient enumeration")
        self.assertTrue(session.enumeration["complete"])
        self.assertEqual(session.errors,{})
        self.assertEqual(session.starts,{"0":1})

if __name__=="__main__": unittest.main(verbosity=2)
