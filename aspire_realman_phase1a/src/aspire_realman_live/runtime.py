"""Factory for unchanged native CAP, EmbeddedAgentRuntime and MCP HTTP server."""
from functools import wraps
from cap_harness.api import CapApi
from cap_harness.contracts import JOINT_DIMENSIONS
from cap_harness.agent.embedded import EmbeddedAgentRuntime
from cap_harness.agent.server import create_app
from cap_harness.registry import ToolRegistry
from aspire_realman.runtime import RealManRuntime
from .adapter import LiveRealManAdapter


MOTION_ENTRIES = ('step', 'execute_trajectory', 'move_to_joints', 'move_to_pose',
    'move_synchronized', 'set_gripper', 'set_grippers', 'open_gripper', 'close_gripper', 'go_home')


class ObservationOnlyCapApi(CapApi):
    @property
    def configured_providers(self):
        return {**super().configured_providers, 'mock_ik_available':False,
                'mock_planner_available':False, 'physical_motion_available':False}


def build_live_runtime(source, *, state_owner=None):
    if JOINT_DIMENSIONS.get('realman') != 6:
        raise RuntimeError('PINNED_ASPIRE_REALMAN_CONTRACT_PATCH_REQUIRED')
    if state_owner is None:
        adapter = LiveRealManAdapter(source)
    else:
        from .state_runtime import SingleArmReadOnlyAdapter
        adapter = SingleArmReadOnlyAdapter(state_owner, camera_source=source)
    # No Mock IK/Planner, no model client, no inferred Home. The configured
    # provider graph truthfully reports segmentation=false and empty planners.
    api = ObservationOnlyCapApi(adapter, home_joint_positions={}, default_camera='tabletop')
    # Bind every CAP motion entry to the adapter's interlock before it can read
    # state, solve IK, infer Home, or invoke any provider. Native signatures are
    # retained for MCP schema generation. Agent decision logic is untouched.
    def refusal_entry(name):
        original = getattr(api,name)
        @wraps(original)
        def refuse(*args, **kwargs):
            if name == 'step':
                return adapter.step(*args, **kwargs)
            return adapter._deny('cap.' + name)
        refuse.__doc__ = 'UNAVAILABLE in Phase 1A; hard safety refusal; no hardware transport. ' + (original.__doc__ or '')
        return refuse
    for name in MOTION_ENTRIES:
        setattr(api,name,refusal_entry(name))
    if state_owner is None:
        registry = api.register_tools(ToolRegistry())
    else:
        from cap_harness.registry import SHARED_PUBLIC_TOOL_NAMES
        registry = api.register_tools(ToolRegistry(shared_public_names=SHARED_PUBLIC_TOOL_NAMES | {'get_readonly_state_snapshot'}))
        registry.register(adapter.get_readonly_state_snapshot, name='get_readonly_state_snapshot',
                          layer='shared_atomic', capability='metadata', public=True)
    runtime = EmbeddedAgentRuntime(api, registry)
    if state_owner is not None:
        from .state_runtime import ReadOnlyStatePrograms
        runtime.session.program_catalog = ReadOnlyStatePrograms()
    try:
        app = create_app(runtime.session)
        return RealManRuntime(adapter, api, runtime, app)
    except BaseException:
        runtime.close()
        adapter.close()
        raise
