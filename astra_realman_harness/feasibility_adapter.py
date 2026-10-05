"""Read-only API2 endpoint IK projection. Never sends motion or configuration calls."""
import copy,ctypes,math,time
from io_utils import vector
from pick_task import pose_preview

SCALES=(1.0,.75,.5,.25,.125,.0625,.03125,.015625,.0078125)
BISECTION_STEPS=6

class FeasibilityError(RuntimeError):pass

def scaled_action(action,scale):
    if not 0<scale<=1:raise ValueError("INVALID_PROJECTION_SCALE")
    out=copy.deepcopy(action)
    if scale==1:return out
    out["translation_m"]=[scale*x for x in action["translation_m"]]
    # Same rotation axis, scaled angle. Do not independently steer RPY axes.
    r,p,y=[v/2 for v in action["rotation_rpy_rad"]]
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    q=[cr*cp*cy+sr*sp*sy,sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,cr*cp*sy-sr*sp*cy]
    if q[0]<0:q=[-v for v in q]
    n=math.sqrt(sum(v*v for v in q[1:]))
    if n<1e-15:out["rotation_rpy_rad"]=[0.,0.,0.]
    else:
        half=math.atan2(n,q[0])*scale;w=math.cos(half)
        x,y,z=[v*math.sin(half)/n for v in q[1:]]
        out["rotation_rpy_rad"]=[math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),
            math.asin(max(-1.,min(1.,2*(w*y-z*x)))),math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))]
    return out

class FeasibilityAdapter:
    def __init__(self,sdk,robot):
        self.sdk,self.robot=sdk,robot
    def project(self,action,state,*,stopping=lambda:False,record=lambda event:None):
        if action.get("arm")!="left" or action.get("gripper")!="hold":raise FeasibilityError("IK_REQUIRES_LEFT_CARTESIAN_ONLY")
        if action.get("frame")!="realman:left:work:World" or action.get("tool_frame")!="realman:left:tool:Arm_Tip":raise FeasibilityError("IK_FRAME_MISMATCH")
        joints=state.get("joint_deg");current=state.get("ee_pose")
        if not vector(joints,6) or not current or not vector(current.get("xyz_m"),3) or not vector(current.get("rpy_rad"),3):raise FeasibilityError("IK_INVALID_CURRENT_STATE")
        trials=[];started=time.monotonic()
        def check(scale):
            if stopping():raise FeasibilityError("HUMAN_STOP")
            candidate=scaled_action(action,scale);target=pose_preview(current,candidate)
            pose=target["xyz_m"]+target["rpy_rad"]
            if any(not math.isfinite(ctypes.c_float(v).value) for v in pose+joints):raise FeasibilityError("IK_FLOAT32_INPUT_INVALID")
            params=self.sdk.rm_inverse_kinematics_params_t(q_in=joints,q_pose=pose,flag=1)
            ret,solution=self.robot.rm_algo_inverse_kinematics(params)
            event={"scale":scale,"return_code":ret,"joint_solution_deg":solution,"target_pose":target,"candidate_action":candidate}
            trials.append(event);record(event)
            if type(ret)is not int or ret not in (0,1):raise FeasibilityError("IK_API_ERROR:"+str(ret))
            if ret==0 and not vector(solution,6):raise FeasibilityError("IK_INVALID_SOLUTION")
            return event if ret==0 else None
        best=None;upper=1.
        for scale in SCALES:
            found=check(scale)
            if found:
                best=found
                break
            upper=scale
        if best is not None and best["scale"]!=1:
            low=best["scale"]
            for _ in range(BISECTION_STEPS):
                midpoint=(low+upper)/2;found=check(midpoint)
                if found:best=found;low=midpoint
                else:upper=midpoint
        return {"status":"FEASIBLE" if best else "INFEASIBLE","original_action":copy.deepcopy(action),
            "selected_action":best["candidate_action"] if best else None,"selected_target":best["target_pose"] if best else None,
            "selected_scale":best["scale"] if best else None,"trials":trials,"latency_s":time.monotonic()-started,
            "search":"original, descending dimensionless scales, six bracket refinements; largest tested feasible scale, not global reachability proof",
            "rotation_projection":"shortest axis-angle interpolation of requested work-frame rotation; same scale as translation",
            "guarantee":"endpoint IK only; not collision/path/singularity certification","motion_commands_sent":0}
