"""GUI binding to existing real parallel-arms runner; no automatic dispatch."""
from astra_gui import Console
from experiment_launch import validate
from real_calibration_status import inventory


class HardwareConsole(Console):
    def __init__(self, *, three_calibration=None, **kwargs):
        super().__init__(**kwargs)
        self.three_calibration=three_calibration

    @staticmethod
    def checked(settings):
        settings=validate(settings)
        if settings['profile']!='parallel':
            raise ValueError('此入口仅连接现有 parallel 双臂真机协议')
        return settings

    def start(self, settings):
        from parallel_safety_pause import require_automation_ready
        require_automation_ready()
        return super().start(self.checked(settings))

    def preflight(self, settings):
        return super().preflight(self.checked(settings))

    def state(self, selected=None):
        value=super().state(selected)
        calibration=inventory(self.three_calibration)
        calibration['limitations']=[
            '使用原 parallel 真机执行链路；不是 chunk_v2 仿真执行器。',
            '左右臂分别使用各自的 World / Arm_Tip；未加入共同基座变换，不进行跨臂坐标换算。',
            '标定仅供查看；不据此自动生成目标或改写模型动作。',
            '保留原状态、IK 与执行检查；未新增共享空间扫掠碰撞保证。',
            '停止按钮等待在途 SDK 返回，不替代硬件急停。',
            '桌面深度历史验证部分失败；右腕留出 RMS 5.45 mm、最大 9.97 mm。']
        value.update(hardware_gui=True,calibration_inventory=calibration,
                     execution_interface='existing_parallel_per_arm_delta')
        return value
