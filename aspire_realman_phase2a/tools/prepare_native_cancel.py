"""Minimal generic native session cancel patch; no Agent decision changes.

The pinned upstream has steering and close(), but no public cancel-job API.
This additive patch requires an explicit operation_controller.cancel_operation;
unsupported controllers fail closed. It never enables a hardware transport.
"""
import argparse,difflib,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
EXPECTED={'session.py':'f15b1a69350e64925665c2cd47a473036279c8bcdc2950df84e5d1293ed354b2',
          'mcp.py':'2dfc9ebc357c89b769e259a1b62044340bf06031990ece318209a201dfa32124',
          'server.py':'02d286c96e1ee6f091e6d19eff6f6d64f038b28ce8b949536a2745c4e38623b4'}

def changes(name,s):
    if name=='session.py':
        s=s.replace('    terminal_state: Any = None\n\n    @property','    terminal_state: Any = None\n    cancellation_requested: bool = False\n\n    @property',1)
        marker='    def job(self, job_id: str | None = None, *, detail: str = "compact")'
        insertion='''    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Request cooperative controller abort for this exact active job.

        A cancellation acknowledgement is not proof of a physical stop. The
        operation result and terminal feedback remain owned by the job thread.
        """
        with self._lock:
            job = self._job
            if job is None or job.id != job_id or not job.active:
                raise ValueError("exact active job_id required for cancellation")
            cancel = getattr(self._operation_controller, "cancel_operation", None)
            if not callable(cancel):
                raise RuntimeError("operation controller does not support cancellation")
            receipt = cancel()
            job.cancellation_requested = True
        self.publish("system", f"cancellation requested [{job_id}]")
        return {"ok": True, "job_id": job_id, "cancellation_requested": True,
                "controller_receipt": receipt}

'''
        assert s.count(marker)==1;s=s.replace(marker,insertion+marker)
        s=s.replace('                "active": job.active,','                "active": job.active,\n                "cancellation_requested": job.cancellation_requested,',1)
    elif name=='mcp.py':
        marker='            ("read_operator_messages", "Drain pending operator instructions.", _object_schema()),'
        assert s.count(marker)==1
        s=s.replace(marker,'''            (
                "cancel_job",
                "Request cooperative cancellation of an exact active job; inspect its terminal result separately.",
                _object_schema({"job_id": {"type": "string"}}, required=["job_id"]),
            ),
'''+marker)
        marker='        if name == "read_operator_messages":'
        assert s.count(marker)==1;s=s.replace(marker,'        if name == "cancel_job":\n            return self.session.cancel_job(args["job_id"]), {}\n'+marker)
    else:
        marker='    return app\n'
        assert s.count(marker)==1
        s=s.replace(marker,'''    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        from fastapi import HTTPException
        try:
            return session.cancel_job(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(501, str(exc)) from exc

'''+marker)
    return s

def main():
    p=argparse.ArgumentParser();p.add_argument('--aspire-source',type=Path,default=ROOT/'.cache/ASPIRE');a=p.parse_args()
    a.aspire_source.resolve().relative_to(ROOT)
    updates=[];patch=[]
    for name,digest in EXPECTED.items():
        path=a.aspire_source/'src/cap_harness/agent'/name;s=path.read_text()
        after=changes(name,s) if hashlib.sha256(s.encode()).hexdigest()==digest else None
        if after is None:raise SystemExit('PRISTINE_PINNED_AGENT_SOURCE_REQUIRED: '+name)
        compile(after,str(path),'exec');updates.append((path,s,after))
        relative='src/cap_harness/agent/'+name
        patch.extend(difflib.unified_diff(s.splitlines(True),after.splitlines(True),fromfile='a/'+relative,tofile='b/'+relative))
    for path,_,after in updates:path.write_text(after)
    (ROOT/'aspire_realman_phase2a/patches/0003-native-session-cancel.patch').write_text(''.join(patch))
    print(json.dumps({str(path):{'before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_sha256':hashlib.sha256(after.encode()).hexdigest()} for path,before,after in updates},indent=2))

if __name__=='__main__':main()
