"""Read-only calibration inventory; never grants hardware execution."""
import hashlib
import json
from pathlib import Path
from io_utils import ROOT

THREE_SHA = '820ea57e341733561768d3a181a4290b71891b358b921fc4de7a68916d5b5264'

def inventory(three_path=None):
    cameras=[]; errors=[]
    sources=[(Path(three_path) if three_path else ROOT/'config/engineering/three_camera_calibration_20261011.json', THREE_SHA),
             (ROOT/'config/engineering/right_wrist_calibration_20261017.json', None)]
    for path, expected in sources:
        try:
            raw=path.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
            if expected and sha!=expected:raise ValueError('SOURCE_HASH_MISMATCH')
            data=json.loads(raw)
            entries=list(data['cameras'].values()) if 'cameras' in data else [data]
            for item in entries:
                cameras.append(dict(role=item['role'],serial=item['serial'],parent_frame=item['parent_frame'],
                    T_parent_camera_optical=item['T_parent_camera_optical'],
                    status=item.get('validation_status',item.get('status')),
                    source=str(path),sha256=sha,details=item))
        except (OSError,ValueError,KeyError) as exc:errors.append(str(path)+': '+str(exc))
    return dict(cameras=cameras,errors=errors,loaded_count=len(cameras),
        real_execution_ready=False,
        limitations=['左右基座共同坐标变换待确认；不得使用仿真 1.1 m 代替实测',
        'TCP 沿用历史值的线索待核对实际配置；不臆造夹垫偏移',
        '桌面相机存在历史深度验证失败；右腕留出 RMS 5.45 mm，最大 9.97 mm',
        '真实双臂碰撞预检、轨迹跟踪、夹爪开度/接触保持与在途停止尚未验收',
        '本入口仅相机观测、标定查看和离线协议回放；模型与运动派发禁用'])
