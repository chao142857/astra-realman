"""Serve only explicit SYNTHETIC data, with no hardware-enable option."""
import argparse,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src')]
from aspire_realman import build_realman_runtime
from aspire_realman.fixtures import synthetic_station,MockSegmentation
import uvicorn
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=18222);a=p.parse_args()
source,config=synthetic_station();runtime=build_realman_runtime(source,config,segmentation_provider=MockSegmentation())
try:uvicorn.run(runtime.app,host='127.0.0.1',port=a.port)
finally:runtime.close()
