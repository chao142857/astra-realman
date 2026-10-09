"""Independent research process smoke check: no robot/controller imports."""
import sys
from pathlib import Path
from platform_client import Client,PlatformError
p=Client();o=p.reset()
assert len(o['rgb'])==3
for camera in ('assembly','fixed','wrist'):assert p.rgb(o,camera).startswith(b'\x89PNG')
assert not Path('/home/alex/astra-realman_ws').exists()
try:p.call('score_private')
except PlatformError as exc:assert str(exc)=='PRIVATE_OR_UNSUPPORTED_METHOD'
else:raise AssertionError('PRIVATE_SCORE_EXPOSED')
print('ISOLATED_MULTICAMERA_AND_PRIVATE_SCORE_DENIAL_OK',file=sys.stderr)
p.finish('unknown')
