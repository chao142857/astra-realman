"""Read-only pre/post snapshot. No robot connections, signals, camera opens or writes."""
import datetime,json,os,pathlib,re,subprocess
P=pathlib.Path;ROOT='/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness'
rows=[]
for p in P('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  if p.stat().st_uid!=os.getuid():continue
  argv=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]
  if not argv:continue
  cwd=os.readlink(str(p/'cwd')); stat=(p/'stat').read_text().rsplit(')',1)[1].split()
  if 'python' not in pathlib.Path(argv[0]).name and p.name not in ['110606']:continue
  if argv[-1:] == ['-']:continue
  fds=[]
  for f in (p/'fd').iterdir():
   try:
    t=os.readlink(str(f))
    if t.startswith('/dev/video') or t.startswith('/dev/bus/usb'):fds.append(t)
   except OSError:pass
  rows.append({'pid':int(p.name),'ppid':int(stat[1]),'state':stat[0],'start_ticks':int(stat[19]),'argv':argv,'cwd':cwd,'device_fds':sorted(set(fds))})
 except OSError:pass
listeners=subprocess.check_output(['ss','-ltnp'],text=True)
sockets=subprocess.check_output(['ss','-tnp'],text=True)
video=subprocess.run(['fuser']+[str(v) for v in P('/dev').glob('video*')],text=True,capture_output=True)
usb=[]
for p in P('/sys/bus/usb/devices').glob('*'):
 try:
  if (p/'idVendor').read_text().strip()=='8086' and (p/'serial').exists():usb.append({k:(p/k).read_text().strip() for k in ['idVendor','idProduct','product','serial'] if (p/k).exists()})
 except OSError:pass
print(json.dumps({'timestamp':datetime.datetime.now().astimezone().isoformat(),'workspace':ROOT,'processes':rows,'listeners':listeners,
 'robot_endpoint_existing_sockets':[l for l in sockets.splitlines() if re.search(r'192\.168\.1\.(18|19):8080',l)],
 'video_owners':{'stdout':video.stdout.strip(),'stderr':video.stderr.strip(),'returncode':video.returncode},'usb':usb},indent=2))
