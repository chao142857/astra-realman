"""Temporary operator pause, explicitly lifted by the user on 2026-10-17.
This flag does not certify collision protection or authorize an episode.
"""
AUTOMATION_PAUSED = False
REASON = ('PARALLEL_AUTOMATION_PAUSED：自动抓取已暂停。实机工具/夹指几何与桌面全过程碰撞保护尚未验收；'
          '终点IK不等于碰撞安全。未启动新的模型回合或自动动作。')

def require_automation_ready():
    if AUTOMATION_PAUSED:
        raise RuntimeError(REASON)
