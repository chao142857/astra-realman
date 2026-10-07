#!/usr/bin/env python3
"""Synthetic apple/tennis-ball sorting episode; no model, SDK, SSH or hardware calls."""
import argparse,json,signal,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT
from bimanual_demo.protocol import action
from bimanual_demo.runtime import Runtime,TaskLock

def run_episode(root,scenario):
    site=json.loads((ROOT/'config/bimanual_synthetic.json').read_text())
    r=Runtime(site,root,{'fruit_01':'apple','clutter_01':'tennis_ball'},{'fruit_01':'fruit','clutter_01':'clutter'})
    signal.signal(signal.SIGINT,lambda *_:r.stop.set())
    def do(kind,obj=None,**kw):
        result=r.execute(action(r.state,kind,obj,**kw))
        print(f"SYNTHETIC | {obj or 'global'} | {kind} | {result['status']} | handoff={r.state.handoff}",flush=True)
        return result
    do('OBSERVE')
    for obj,cls in [('fruit_01','fruit'),('clutter_01','clutter')]:
        destination='plate' if cls=='fruit' else 'box'
        do('SELECT_OBJECT',obj,semantic_class=cls,destination=destination)
        do('LEFT_PICK',obj);do('LEFT_PRESENT',obj)
        if scenario=='handoff-failure' and obj=='fruit_01':r.observer.fail_events.add('RIGHT_HOLDING_CONFIRMED')
        if scenario=='unknown-ack' and obj=='fruit_01':r.arms['right'].fail_next='synthetic ACK timeout'
        result=do('BIMANUAL_HANDOFF',obj)
        if result['status']=='RECOVER_REQUIRED':
            calls_before=sum(len(a.calls) for a in r.arms.values())
            # Explicit synthetic recovery decision; no command is retried by the executor.
            if scenario=='handoff-failure':
                r.observer.fail_events.clear();r.observer.recovery={'holder':'left','checkpoint':'RIGHT_HOLDING_CONFIRMED','both_holding':True}
            else:r.observer.recovery={'holder':'left','checkpoint':'LEFT_AT_HANDOFF'}
            do('RECOVER',obj)
            assert calls_before==sum(len(a.calls) for a in r.arms.values())
            do('BIMANUAL_HANDOFF',obj)
        do('RIGHT_PLACE',obj,destination=destination);do('VERIFY',obj)
    summary=r.recorder.export(r.state)
    assert summary['completed_objects']==['fruit_01','clutter_01']
    assert summary['real_hardware_calls']==summary['real_model_calls']==0
    print(json.dumps({'run':str(root),'scenario':scenario,'completed':summary['completed_objects'],'real_model_calls':0,'real_hardware_calls':0,'archive':str(root/'capture_snapshot.zip')},ensure_ascii=False))
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scenario',choices=['nominal','handoff-failure','unknown-ack','all'],default='all')
    args=p.parse_args();folder=ROOT/'logs'/('bimanual-synthetic-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    # Isolated synthetic lock: no access to a live robot lock or running episode.
    with TaskLock(folder/'synthetic.lock'):
        for scenario in (['nominal','handoff-failure','unknown-ack'] if args.scenario=='all' else [args.scenario]):run_episode(folder/scenario,scenario)
if __name__=='__main__':main()
