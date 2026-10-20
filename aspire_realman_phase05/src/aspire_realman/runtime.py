"""Use native CapApi, persistent EmbeddedAgentRuntime and MCP transport unchanged."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from cap_harness.api import CapApi
from cap_harness.agent.embedded import EmbeddedAgentRuntime
from cap_harness.agent.server import create_app
from cap_harness.contracts import IKResult, JOINT_DIMENSIONS, SynchronizedPlanResult
from cap_harness.errors import ApiError, ErrorCode
from cap_harness.registry import ToolRegistry
from .adapter import RealManAdapter
from .codec import CodecConfig
from .sources import MemorySource


class RefusingIK:
    """Advertise the native pose tool while refusing all planning, no HTTP client."""
    def solve_ik(self, *args, **kwargs):
        return IKResult(ok=False, error=ApiError(ErrorCode.SAFETY_INTERLOCK, 'Offline runtime: IK/physical dispatch disabled'))


class RefusingPlanner:
    def plan_synchronized_motion(self, *args, **kwargs):
        return SynchronizedPlanResult(ok=False, error=ApiError(ErrorCode.SAFETY_INTERLOCK, 'Offline runtime: synchronized planning disabled'))


@dataclass
class RealManRuntime:
    adapter: RealManAdapter
    api: CapApi
    runtime: EmbeddedAgentRuntime
    app: Any

    def close(self) -> None:
        self.runtime.close()
        self.adapter.close()


def build_realman_runtime(source: MemorySource, config: CodecConfig, *, segmentation_provider=None) -> RealManRuntime:
    if JOINT_DIMENSIONS.get('realman') != 6:
        raise RuntimeError('PINNED_ASPIRE_REALMAN_CONTRACT_PATCH_REQUIRED')
    adapter = RealManAdapter(source, config)
    # Empty explicit home map: do not silently remember current pose as Home.
    api = CapApi(adapter, home_joint_positions={}, default_camera=source.read()['cameras'][0]['role'],
                 segmentation_provider=segmentation_provider, ik_providers={'curobo': RefusingIK()},
                 integrated_pose_planning_providers={'curobo-integrated': RefusingPlanner()})
    registry = api.register_tools(ToolRegistry())
    runtime = EmbeddedAgentRuntime(api, registry)
    try:
        app = create_app(runtime.session)
        runtime.session.visual_snapshot()
        return RealManRuntime(adapter, api, runtime, app)
    except BaseException:
        runtime.close(); adapter.close()
        raise
