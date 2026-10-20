"""Native CAP, EmbeddedAgentRuntime, server and MCP unchanged; Stub adapter only."""
from cap_harness.api import CapApi
from cap_harness.contracts import MotionStrategy
from cap_harness.agent.embedded import EmbeddedAgentRuntime
from cap_harness.agent.server import create_app
from cap_harness.registry import ToolRegistry
from aspire_realman.runtime import RealManRuntime
from .adapter import OfflineRealManAdapter


def build_runtime(manifest,ledger,provider,*,segmentation_provider=None):
    adapter=OfflineRealManAdapter(manifest,ledger,provider=provider)
    api=CapApi(adapter,home_joint_positions={},default_camera='synthetic_overhead',segmentation_provider=segmentation_provider,
        ik_providers={'curobo':provider} if provider else {},trajectory_planning_providers={'curobo':provider} if provider else {},
        integrated_pose_planning_providers={'curobo-integrated':provider} if provider else {},
        default_motion_strategy=MotionStrategy(ik_solver='curobo',trajectory_planner='curobo',pose_planner='curobo-integrated'))
    registry=api.register_tools(ToolRegistry());runtime=EmbeddedAgentRuntime(api,registry)
    return RealManRuntime(adapter,api,runtime,create_app(runtime.session))
