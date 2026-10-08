#!/usr/bin/env python3
"""Summarize offline E1-B artifacts and export a labeled, static SVG timeline."""
import argparse
import html
import json
from pathlib import Path


def intervals(events,start,end):
    pending=[];out=[]
    for e in events:
        if e['kind']==start:pending.append(e)
        elif e['kind']==end and pending:out.append((pending.pop(0),e))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args()
    rows=[];tracks=[]
    for path in sorted(a.root.glob('*/result.json')):
        r=json.loads(path.read_text());s=r.get('episode',{})
        timeline=path.parent/'episode/timeline.jsonl'
        events=[json.loads(line) for line in timeline.read_text().splitlines()] if timeline.exists() else []
        actions=intervals(events,'PRIMITIVE_START','PRIMITIVE_END')
        overlap=0.;worker=[]
        origin=events[0]['wall_monotonic']-events[0]['wall_elapsed_s'] if events else 0
        for e in events:
            if e['kind']=='REQUEST_END' and e['data'].get('record'):
                rec=e['data']['record'];start=rec['worker_started_monotonic'];end=rec['worker_finished_monotonic']
                worker.append((start-origin,end-origin))
                overlap+=sum(max(0,min(end,b['wall_monotonic'])-max(start,c['wall_monotonic'])) for c,b in actions)
        row={'run':path.parent.name,'backend':r['backend'],'condition':s.get('condition'),'scenario':s.get('scenario'),
             'case':s.get('case'),'status':r['status'],'stub_calls':s.get('stub_calls'),
             'model_calls':r['model_calls'],'hardware_calls':r['hardware_calls'],
             'worker_motion_overlap_s':overlap,'initialization_wall_s':r.get('initialization_wall_s'),
             'initialization_physics_s':r.get('initialization_physics_s'),'cold_start_s':s.get('cold_start_s'),
             'placement_wall_s':s.get('wall_s'),'placement_physics_s':s.get('physics_s'),
             'primitive_sequence':[v['name'] for v in s.get('primitive_sequence',[])],
             'primitive_sequence_sha256':s.get('primitive_sequence_sha256'),'evaluation':s.get('evaluation'),
             'faults':[e for e in events if e['kind'] in ('FAULT','CANDIDATE_REJECTED','STOP','REQUEST_CANCELLED')]}
        rows.append(row)
        if r['backend']=='sapien':tracks.append((path.parent.name,s,actions,worker,events))
    (a.root/'rollup.json').write_text(json.dumps({'scope':'OFFLINE_DELAYED_STUB_NOT_ASTRA','rows':rows},indent=2)+'\n')
    lines=['# E1-B offline delayed stub acceptance','',
           '**DELAYED_STUB_NOT_ASTRA. Protocol test doubles have no physical score. No real-model speedup claim.**','',
           '| run | status | stub calls | init wall / physics s | cold s | placement wall / physics s | stub-motion overlap s |',
           '|---|---|---:|---:|---:|---:|---:|']
    def f(n):return '—' if n is None else '%.3f'%n
    for r in rows:
        lines.append('| %s | %s | %s | %s / %s | %s | %s / %s | %s |'%(r['run'],r['status'],r['stub_calls'],
          f(r['initialization_wall_s']),f(r['initialization_physics_s']),f(r['cold_start_s']),f(r['placement_wall_s']),f(r['placement_physics_s']),f(r['worker_motion_overlap_s'])))
    lines+=['','Overlap uses the intersection of worker process timestamps with executed primitive intervals, excluding holding and evaluation.',
            'All JSONL timelines, input snapshots, hashes, worker records, cancellations, simulator logs and videos remain in their run directories.',
            'Placement wall includes initial observation, cold start, rendering, inference waits, motion, idle holding and independent evaluation. Initialization is separate.']
    (a.root/'REPORT.md').write_text('\n'.join(lines)+'\n')
    if tracks:
        width=1100;height=100+150*len(tracks);scale=850/max(t[1]['wall_s'] for t in tracks)
        svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="sans-serif" font-size="13" fill="#172b4d">',
             '<text x="20" y="25" font-size="19">E1-B offline / DELAYED STUB, NOT ASTRA</text>',
             '<text x="20" y="50">Green: approved primitive execution. Purple: stub worker. Gray: holding. Wall seconds from placement start.</text>']
        def bar(start,end,y,color,label):
            svg.append(f'<rect x="{200+start*scale:.2f}" y="{y}" width="{max(1,(end-start)*scale):.2f}" height="18" fill="{color}"><title>{html.escape(label)}</title></rect>')
        for i,(name,s,actions,worker,events) in enumerate(tracks):
            y=85+i*150
            svg.append(f'<text x="20" y="{y+14}">{html.escape(name)}</text>')
            for begin,end in intervals(events,'HOLD_BEGIN','HOLD_END'):bar(begin['wall_elapsed_s'],end['wall_elapsed_s'],y,'#9ca3af','holding')
            for begin,end in actions:bar(begin['wall_elapsed_s'],end['wall_elapsed_s'],y,'#047857',begin['data']['primitive']['name'])
            for start,end in worker:bar(start,end,y+28,'#7c3aed','stub worker')
            for e in events:
                if e['kind'] in ('PUBLIC_TASK_UPDATE','CANDIDATE_ADOPTED','JOIN_OBSERVATION'):
                    x=200+scale*e['wall_elapsed_s'];svg.append(f'<path d="M{x:.2f},{y-5} v55" stroke="#f97316"><title>{e["kind"]}</title></path>')
            for tick in range(int(s['wall_s'])+1):
                x=200+scale*tick;svg.append(f'<text x="{x:.2f}" y="{y+68}" text-anchor="middle">{tick}</text>')
            svg.append(f'<text x="200" y="{y+94}">physics {s["physics_s"]:.3f}s / wall {s["wall_s"]:.3f}s; dt={s["dt"]}s; same pacing rule</text>')
        svg+=['</g></svg>'];(a.root/'timeline.svg').write_text('\n'.join(svg))
    print(json.dumps({'runs':len(rows),'model_calls':sum(r['model_calls'] for r in rows),'hardware_calls':sum(r['hardware_calls'] for r in rows)}))

if __name__=='__main__':main()
