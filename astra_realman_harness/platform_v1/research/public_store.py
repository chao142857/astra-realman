"""Owner registry of immutable PUBLIC records; callers supply IDs, never host paths."""
import hashlib
import time
from pathlib import Path
from .contracts import clone, digest, WORLD_VERSION

class PublicStore:
    def __init__(self, root, episode_id):
        self.root = Path(root).resolve(); self.episode_id = episode_id
        self.observations = {}; self.evidence = {}; self.worlds = {}; self.revision = 0
        self.current_world_id = None

    def observe(self, observation, epoch):
        o = clone(observation)
        if o['episode_id'] != self.episode_id: raise ValueError('OBSERVATION_EPISODE')
        o['execution_epoch'] = epoch
        identity = o['observation_id']
        if identity in self.observations and self.observations[identity] != o:
            raise ValueError('IMMUTABLE_OBSERVATION')
        self.observations[identity] = o

    def get(self, identity):
        if identity not in self.observations: raise ValueError('UNKNOWN_PUBLIC_OBSERVATION')
        return clone(self.observations[identity])

    def image(self, identity, camera):
        o = self.get(identity)
        item = next((r for r in o['rgb'] if r['camera'] == camera), None)
        if item is None: raise ValueError('UNKNOWN_CAMERA')
        path = (self.root / item['file']).resolve()
        if not path.is_relative_to(self.root): raise ValueError('PUBLIC_PATH_ESCAPE')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256'] or not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('PUBLIC_RGB_HASH')
        return data, item

    def evidence_record(self, request_id, role, result, provenance, observations, attachments):
        record = {'request_id': request_id, 'role': role, 'result': clone(result),
            'provenance': provenance, 'observation_ids': list(observations),
            'attachments': clone(attachments), 'recorded_monotonic': time.monotonic(),
            'identity_validity': 'MODEL_HYPOTHESIS_NOT_GROUND_TRUTH'}
        identity = 'e-' + digest(record); record['evidence_id'] = identity
        self.evidence[identity] = record
        return clone(record)

    def get_evidence(self, identity):
        if identity not in self.evidence: raise ValueError('UNKNOWN_EVIDENCE_ID')
        return clone(self.evidence[identity])

    def get_world(self, identity):
        if identity not in self.worlds: raise ValueError('UNKNOWN_WORLD_ID')
        return clone(self.worlds[identity])

    def publish_world(self, report, binding, provenance):
        self.revision += 1
        state = {'version': WORLD_VERSION, 'world_revision': self.revision,
            'binding': clone(binding), 'created_monotonic': time.monotonic(),
            'state': clone(report), 'provenance': provenance,
            'semantics': 'COARSE_ESTIMATE_NOT_SIMULATOR_TRUTH'}
        identity = 'w-' + digest(state); state['world_id'] = identity
        self.worlds[identity] = state; self.current_world_id = identity
        return clone(state)
