"""Narrow operator-authorized shutdown. Default is inspection; --sigint/--sigterm only.
Matches current user, exact argv/cwd/start_ticks from fresh reviewed snapshot;
refuses to act with any other Python process in the experiment workspaces or
existing robot endpoint socket. Sends to individual PIDs, never groups.
"""
import datetime,json,os,pathlib,signal,subprocess,sys,time
P=pathlib.Path
EXPECTED = []  # populated by the local caller from the reviewed preflight snapshot

def identity(pid):
 p=P('/proc')/str(pid)
 try:
  if p.stat().st_uid!=os.getuid():raise RuntimeError('OWNER_MISMATCH')
  st=(p/'stat').read_text().rsplit(')',1)[1].split()
  return {'pid':pid,'argv':(p/'cmdline').read_bytes().decode().split('\0')[:-1],
          'cwd':os.readlink(str(p/'cwd')),'start_ticks':int(st[19]),'state':st[0]}
 except FileNotFoundError:return None

def guard():
 allowed={e['pid'] for e in EXPECTED}
 for p in P('/proc').iterdir():
  if not p.name.isdigit() or int(p.name) in allowed or int(p.name)==os.getpid():continue
  try:
   a=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]
   if a and 'python' in P(a[0]).name and any('/home/tongji/alex/' in v for v in a):
    raise RuntimeError('UNREVIEWED_EXPERIMENT_PROCESS:'+p.name)
  except (FileNotFoundError,PermissionError):pass
 sockets=subprocess.check_output(['ss','-tnp'],text=True)
 if any(x in sockets for x in ['192.168.1.18:8080','192.168.1.19:8080']):raise RuntimeError('EXISTING_ROBOT_CONNECTION')

requested=sys.argv[1:]
if requested not in [[],['--sigint'],['--sigterm']]:raise SystemExit('Unsupported operation')
guard();events=[]
for e in EXPECTED:
 current=identity(e['pid'])
 if current is None or current.get('state')=='Z':
  events.append({'pid':e['pid'],'outcome':'ALREADY_EXITED'});continue
 if any(current[k]!=e[k] for k in ['argv','cwd','start_ticks']):raise RuntimeError('PID_IDENTITY_CHANGED:'+str(e['pid']))
 if not requested:events.append(current);continue
 guard()
 sig=signal.SIGINT if requested==['--sigint'] else signal.SIGTERM
 os.kill(e['pid'],sig);events.append({'pid':e['pid'],'signal':sig.name,'sent_at':time.time()})
# Bounded wait, no escalation or retries hidden in this script.
end=time.monotonic()+12
while requested and time.monotonic()<end:
 live=[e['pid'] for e in EXPECTED if (identity(e['pid']) or {}).get('state') not in [None,'Z']]
 if not live:break
 time.sleep(0.25)
for e in events:
 final=identity(e['pid']);e['final_state']='EXITED' if final is None else final['state']
print(json.dumps({'timestamp':datetime.datetime.now().astimezone().isoformat(),
 'mode':requested or ['inspect'],'user_reported_robot_power_off':True,
 'activity_checks':'no unreviewed experiment Python process or existing arm endpoint socket',
 'events':events},indent=2))
