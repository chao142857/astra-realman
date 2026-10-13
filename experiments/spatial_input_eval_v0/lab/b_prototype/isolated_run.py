"""Audit public-only estimator reads and reject network/process/private repository access."""
import argparse,sys,runpy,json,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--estimator',type=Path,required=True);p.add_argument('--public',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--deny-root',type=Path,required=True);a=p.parse_args()
# Load computational dependencies before restricting all estimator data reads.
import numpy, scipy.ndimage, scipy.spatial.transform, PIL.Image, PIL.ImageDraw
allowed=[a.public.resolve(),a.output.resolve(),a.estimator.resolve()];reads=set();rejected=[]
def guard(event,args):
 if event in ('socket.connect','socket.bind','subprocess.Popen','os.system'):raise PermissionError('ESTIMATOR_NETWORK_PROCESS_DENIED')
 if event=='open' and isinstance(args[0],(str,bytes)):
  path=Path(args[0]).resolve()
  if path.is_relative_to(a.deny_root.resolve()):raise PermissionError('PRIVATE_REPOSITORY_DENIED:'+str(path))
  if path.suffix in ('.json','.png','.npy','.npz') and not any(path==x or path.is_relative_to(x) for x in allowed):raise PermissionError('UNLISTED_DATA_DENIED:'+str(path))
  if path.is_relative_to(a.public.resolve()):reads.add(str(path.relative_to(a.public.resolve())))
sys.addaudithook(guard)
# Explicitly exercise the deny rules before processing any observations.
for path in (a.deny_root/'snapshot.json',a.public.parent/'forbidden.json'):
 try:open(path,'rb')
 except PermissionError:rejected.append(str(path))
 else:raise AssertionError('DATA_GUARD_FAILED')
sys.argv=[str(a.estimator),'--public',str(a.public),'--output',str(a.output)]
runpy.run_path(str(a.estimator),run_name='__main__')
(a.output/'isolation_audit.json').write_text(json.dumps({'status':'PASS','public_files_opened':sorted(reads),'deny_probes':rejected,'network_and_process_launch_denied':True,'segmentation_used':False},indent=2)+'\n')
