#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import strict_json,output_path,write_json
from observation import capture_camera
config=strict_json(sys.argv[1]);run=output_path(sys.argv[2])
result=run/("camera-"+config["serial"]+".json")
try:
    data=capture_camera(config,run)
    write_json(result,data)
except Exception as exc:
    write_json(result,{"error":str(exc)[:1000],"error_type":type(exc).__name__})
    sys.exit(2)
