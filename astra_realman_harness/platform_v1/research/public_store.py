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
        self.read_versions = {}
        # Trusted host receipts; never taken from model output or WorldQuery.
        self.grounding_sources = {}
        self.semantic_world_pins = {}
        self.geometry_update_receipts = {}

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
        if role in ('action_shadow','semantic_grounding'):
            record.update(grants_execution=False, execution_class='REVIEW_ONLY')
        identity = 'e-' + digest(record); record['evidence_id'] = identity
        self.evidence[identity] = record
        return clone(record)

    def depth(self, identity, camera):
        from .rgbd_sensor import load_depth
        return load_depth(self,identity,camera)

    def get_evidence(self, identity):
        if identity not in self.evidence: raise ValueError('UNKNOWN_EVIDENCE_ID')
        return clone(self.evidence[identity])

    def get_world(self, identity):
        if identity not in self.worlds: raise ValueError('UNKNOWN_WORLD_ID')
        return clone(self.worlds[identity])

    def get_object(self, world_id, instance_id):
        """Revision-bound object query; historical/predicted/current stay distinct."""
        world=self.get_world(world_id)
        if instance_id not in world['state'].get('entities',{}):raise ValueError('UNKNOWN_INSTANCE_ID')
        return {'world_id':world_id,'world_revision':world['world_revision'],
            'read_versions':world['read_versions'],'provenance':world['provenance'],
            'object':clone(world['state']['entities'][instance_id]),'grants_execution':False}

    def query_world(self, world_id, entity_ids=None, max_bytes=128*1024):
        """Compact revision-bound projection; full geometry remains in this Store."""
        from .model_context import compact_world
        return compact_world(self.get_world(world_id),entity_ids,max_bytes)

    def publish_world(self, report, binding, provenance, read_versions=None):
        if read_versions is not None: self.read_versions = clone(read_versions)
        self.revision += 1
        state = {'version': WORLD_VERSION, 'world_revision': self.revision,
            'binding': clone(binding), 'created_monotonic': time.monotonic(),
            'state': clone(report), 'provenance': provenance, 'read_versions': clone(self.read_versions),
            'semantics': 'COARSE_ESTIMATE_NOT_SIMULATOR_TRUTH'}
        identity = 'w-' + digest(state); state['world_id'] = identity
        self.worlds[identity] = state; self.current_world_id = identity
        return clone(state)
