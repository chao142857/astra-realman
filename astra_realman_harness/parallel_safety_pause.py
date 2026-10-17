"""Incident pause. No CLI bypass; remove only after reviewed real geometry integration."""
REASON = ('PARALLEL_AUTOMATION_PAUSED: real tool/finger geometry and table swept-collision '
          'protection are not validated. Endpoint IK is not collision clearance. '
          'New model episodes and real automatic actions are disabled pending review.')

def require_automation_ready():
    raise RuntimeError(REASON)
