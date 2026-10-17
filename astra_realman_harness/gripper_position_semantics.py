"""Opening quantization tolerance only; never establishes object contact/holding."""
def evaluation(g,target,tolerance):
    raw=g.get('raw',{});position=g.get('position');speed=raw.get('speed',[None])[0]
    healthy=raw.get('sys_state')==0 and bool(raw.get('dof_err')) and raw['dof_err'][0]==0
    reached=(isinstance(position,(int,float)) and abs(position-target)<=tolerance and speed==0 and healthy)
    return {'target_raw':target,'measured_raw':position,'error_raw':position-target if isinstance(position,(int,float)) else None,
            'tolerance_raw':tolerance,'stationary':speed==0,'healthy':healthy,'opening_reached':reached,
            'grasp_confirmed':'UNKNOWN','quantity':'opening, not force or object contact'}
