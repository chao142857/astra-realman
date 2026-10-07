#!/usr/bin/env python3
"""Export one recorded request prefix; no inference, SDK or future-frame replay."""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim_skills.model import input_payload
from sim_skills.projection import history_projection, image_projection


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events', type=Path, required=True)
    p.add_argument('--request-index', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cameras', nargs='+', default=['assembly','fixed','wrist'])
    p.add_argument('--resize', nargs=2, type=int)
    p.add_argument('--history', choices=('raw','lossless'), default='raw')
    p.add_argument('--history-budget-bytes', type=int, default=65536)
    a = p.parse_args()
    # Stop at the requested MODEL_ATTEMPT; evaluator and all future lines are unread.
    count = 0; context = None
    with a.events.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['kind'] == 'MODEL_ATTEMPT':
                count += 1
                if count == a.request_index:
                    context = row['data']['context']; break
    if context is None:raise ValueError('REQUEST_NOT_FOUND')
    a.output.mkdir(parents=True, exist_ok=False)
    payload = input_payload(context)
    selected, image_meta = image_projection(context['observation']['images'], a.output/'input_only',
        cameras=a.cameras, resize=a.resize, online_phase={'source':'scheduler_completed_prefix',
                                                         'primitive_index':context['binding']['primitive_index']})
    safe = payload['context']
    safe['images_in_attachment_order'] = [{**r, 'file':Path(r['file']).name,
                                           'observation_id':context['observation']['observation_id']} for r in selected]
    history, history_meta = history_projection(safe['previous_feedback'], mode=a.history,
                                               budget_bytes=a.history_budget_bytes)
    safe['previous_feedback'] = history
    if history_meta['actual_mode'] == 'lossless':
        safe['history_encoding'] = history['guide']
    (a.output/'input_only/context.json').write_text(json.dumps(safe, indent=2))
    (a.output/'input_only/schema.json').write_text(json.dumps(payload['schema'], indent=2))
    manifest = {'source_event_log':str(a.events), 'binding':context['binding'],
                'images':selected, 'image_projection':image_meta, 'history_projection':history_meta,
                'real_model_calls':0, 'hardware_calls':0, 'physics_calls':0,
                'request_eligible':history_meta['eligible'], 'diagnostics':'D0',
                'scope':'development projection; not the missing formal E2/E3 cards or H5D1 32-request matrix'}
    (a.output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'output':str(a.output),'eligible':manifest['request_eligible'], 'model_calls':0}))


if __name__ == '__main__':main()
