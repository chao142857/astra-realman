"""Native adapter extension: camera monitor works without inventing RobotState."""
import time
from cap_harness.errors import ApiError, ErrorCode
from aspire_realman.adapter import RealManAdapter
from aspire_realman.codec import ObservationUnavailable
from .source import LiveSource
from .quality import camera_quality


class LiveRealManAdapter(RealManAdapter):
    def __init__(self, source: LiveSource):
        if type(source) is not LiveSource:
            raise TypeError('LIVE_OWNER_SOURCE_REQUIRED')
        self._source = source
        self._expected_cameras = dict(source.roles)
        self._closed = False
        self._refusals = []

    @property
    def arms(self):
        return ('left','right')

    def _error(self, operation):
        self._refusals.append({'operation':operation,'timestamp_s':time.time(),'hardware_commands_sent':0})
        return ApiError(ErrorCode.SAFETY_INTERLOCK,
            'Phase 1A observation-only: physical dispatch is unavailable; no hardware command transport',
            recoverable=False, details={'operation':operation,'hardware_commands_sent':0,'dispatch_attempted':False})

    def get_robot_state(self):
        raise ObservationUnavailable('REAL_ROBOT_STATE_UNAVAILABLE_ARMS_POWERED_OFF; no SDK connection or synthetic fallback')

    def get_observation(self):
        # Native Observation requires a genuine RobotState. Monitor-only camera
        # evidence is not cast to an incomplete or fake native Observation.
        self.get_robot_state()

    def get_task_context(self):
        raise ObservationUnavailable('NO_REAL_TASK_STARTED_PHASE_1A')

    def monitor_snapshot(self):
        snapshot = self._read()
        cameras = snapshot['cameras']
        metadata = {c['role']:camera_quality(c,snapshot) for c in cameras}
        return {'ok':True, 'timestamp_s':snapshot['captured_at'], 'refresh_timestamp_s':time.time(),
            'observation_seq':snapshot['sequence'], 'cameras':{c['role']:c['rgb'] for c in cameras},
            'camera_metadata':metadata, 'state':{}}
