"""Non-generating link check: GET / is unsupported (501) by the original Handler."""
import datetime,json,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
remote='''import http.client,json,subprocess
conn=http.client.HTTPConnection("127.0.0.1",18766,timeout=5)
conn.request("GET","/")
response=conn.getresponse();body=response.read(8192)
record={"method":"GET","path":"/","http_status":response.status,"server":response.getheader("Server"),"expected_status":501,"decide_requests":0,"model_requests":0}
conn.close()
record["listener"]=subprocess.check_output(["ss","-ltnp","sport = :18766"],text=True)
print(json.dumps(record))'''
probe=subprocess.run(['ssh','yanglab','/usr/bin/python3 -c '+shlex.quote(remote)],capture_output=True,text=True,timeout=15)
assert probe.returncode==0,probe.stderr
record=json.loads(probe.stdout)
record['checked_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
listener=subprocess.run(['lsof','-nP','-iTCP:18767','-sTCP:LISTEN'],capture_output=True,text=True)
record['mac_listener']=listener.stdout
assert listener.returncode==0 and record['http_status']==501
assert 'Python/3.11.16' in record['server'],record['server']
record['status']='PASS_TRANSPORT_ONLY_NOT_MODEL_READINESS'
record['production_code_modified']=False
(root/'link_check.json').write_text(json.dumps(record,indent=2)+'\n')
(root/'service_log_snapshot.txt').write_bytes(Path('/private/tmp/astra-spatial-mac-bridge-service-20261013.log').read_bytes())
print(json.dumps(record,indent=2))
