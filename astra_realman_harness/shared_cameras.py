"""Local GUI-owned camera streams. Robot state and commands remain in the original runner."""
import json
import os
import urllib.request
from urllib.parse import urlparse

class SharedCameraSession:
    def __init__(self, configs, **kwargs):
        self.configs=list(configs)
        self.url=os.environ['ASTRA_CAMERA_HUB_URL']
        self.token=os.environ['ASTRA_CAMERA_HUB_TOKEN']
        u=urlparse(self.url)
        if u.scheme!='http' or u.hostname!='127.0.0.1':raise ValueError('LOCAL_CAMERA_HUB_REQUIRED')
    def __enter__(self):return self
    def __exit__(self,*args):pass  # The GUI owns the physical streams, not this child.
    def snapshot(self,run):
        req=urllib.request.Request(self.url+'/api/capture',data=json.dumps({'path':str(run),'cameras':self.configs}).encode(),
            headers={'Content-Type':'application/json','X-Astra-Token':self.token})
        with urllib.request.urlopen(req,timeout=35) as response:
            result=json.loads(response.read(4*1024*1024))
        if 'error' in result:raise RuntimeError(result['error'])
        return result['images'],result['failures'],result['metrics']
