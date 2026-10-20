"""Immutable CPU snapshots; never create a device, SDK, socket or subprocess."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import threading
from typing import Any
import numpy as np


class MemorySource:
    """Caller-owned, already acquired data. A read returns one coherent copy."""
    def __init__(self, snapshot: dict[str, Any]):
        if snapshot.get('mode') not in {'SYNTHETIC', 'REPLAY_METADATA_ONLY', 'HISTORICAL_REPLAY'}:
            raise ValueError('Phase0.5 sources must be explicitly synthetic/replay')
        self._snapshot = copy.deepcopy(snapshot)
        self._lock = threading.Lock()
        self.closed = False

    def publish(self, snapshot: dict[str, Any]) -> None:
        """Atomically replace one complete owner-produced snapshot; never acquire data."""
        with self._lock:
            if self.closed:
                raise RuntimeError('SOURCE_CLOSED')
            if snapshot.get('mode') != self._snapshot['mode']:
                raise ValueError('SOURCE_KIND_CANNOT_CHANGE')
            sequence = snapshot.get('sequence')
            if type(sequence) is not int or sequence <= self._snapshot.get('sequence', 1):
                raise ValueError('CACHE_SEQUENCE_NOT_INCREASING')
            self._snapshot = copy.deepcopy(snapshot)

    def read(self) -> dict[str, Any]:
        with self._lock:
            if self.closed:
                raise RuntimeError('SOURCE_CLOSED')
            return copy.deepcopy(self._snapshot)

    def close(self) -> None:
        with self._lock:
            self.closed = True


class ReplaySource(MemorySource):
    """A recorded observation, never its proposal/execution script.

    Without assets_root, recorded image paths are metadata only and never opened.
    With it, every read is confined to that explicit local directory and must
    match a recorded SHA256. No downloading or automatic replay advancement.
    """
    def __init__(self, path: Path | str, *, assets_root: Path | str | None = None):
        path = Path(path).resolve()
        raw = path.read_bytes()
        snapshot = json.loads(raw)
        if 'canonical_states' not in snapshot:
            raise ValueError('REPLAY_CANONICAL_STATE_MISSING')
        snapshot['mode'] = 'HISTORICAL_REPLAY'
        snapshot['replay_file'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        if assets_root is not None:
            root = Path(assets_root).resolve(strict=True)
            for camera in snapshot.get('cameras', []):
                image = self._asset(root, camera['image_path'], camera['sha256'])
                from PIL import Image
                with Image.open(image) as frame:
                    camera['rgb'] = np.array(frame.convert('RGB'))
                if camera.get('depth_path'):
                    depth = self._asset(root, camera['depth_path'], camera['depth_sha256'])
                    camera['depth_m'] = np.load(depth, allow_pickle=False)
        super().__init__(snapshot)

    @staticmethod
    def _asset(root: Path, name: str, expected: str) -> Path:
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('REPLAY_ASSET_OUTSIDE_EXPLICIT_ROOT')
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('REPLAY_ASSET_TOO_LARGE')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('REPLAY_ASSET_HASH_MISMATCH')
        return path
