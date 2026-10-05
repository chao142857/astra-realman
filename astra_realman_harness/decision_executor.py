"""Shadow-only sink. Outcome labels cannot enable actuation."""
from abc import ABC, abstractmethod

class Executor(ABC):
    @abstractmethod
    def submit(self, proposal, safety_result):
        pass

class DryRunExecutor(Executor):
    def execution_readiness(self):
        return {
            "operator_authorization":{"status":"NOT_GRANTED","evidence":"User requires zero motion."},
            "trajectory_validation":{"status":"UNCONFIRMED","evidence":None},
            "hardware_executor":{"status":"NOT_IMPLEMENTED","evidence":"This class only records logs."}
        }

    def submit(self, proposal, safety_result):
        outcome=safety_result.get("outcome",safety_result.get("decision"))
        status={"PASS_NOOP":"NOOP_LOGGED","PASS_EXECUTABLE":"SHADOW_PROPOSAL_LOGGED",
                "REJECT":"REJECTED"}.get(outcome,"REJECTED")
        return {"executor":"DryRunExecutor","mode":"shadow_only","status":status,
                "proposal":proposal,"safety_decision":outcome,
                "execution_permitted":False,"hardware_commands_sent":0,"motion_commands_sent":0,
                "post_execution_observation":None,
                "reason":"NOOP is not sent to hardware. Nonzero proposals are logged only; no motion backend exists."}
