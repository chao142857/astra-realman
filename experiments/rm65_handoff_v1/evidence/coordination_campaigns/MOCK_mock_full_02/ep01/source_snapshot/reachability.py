import numpy as np,json
from dual_scene import DualScene,RM65Scene
w=DualScene('evidence/reachability_01');out=[]
try:
 a=w.arms['left'];r=RM65Scene.move_tcp(a,[.25,-.18,.18,0,1,0,0]);print('LEFT_PARK',r['ok'],flush=True)
 for s,points,q in [('right',[[x,0,z] for x in [.45,.5,.54] for z in [.18,.08,.04]],[0,0,1,0]),('left',[[.27,0,.22],[.3,0,.2]],[0,1,0,0])]:
  arm=w.arms[s];arm.init_planner();old=arm.motion.IK
  def verbose(*args,**kwargs):return old(*args,**dict(kwargs,verbose=True))
  arm.motion.IK=verbose
  for p in points:
   print('GOAL',s,p,flush=True)
   try:
    plan=arm.plan_tcp([*p,*q]);row={'arm':s,'p':p,'status':'PASS','q':plan['position'][-1].tolist()}
   except Exception as e:row={'arm':s,'p':p,'status':str(e)}
   out.append(row);print('RESULT',row,flush=True)
 (w.output/'goals.json').write_text(json.dumps(out,indent=2))
finally:w.close()
