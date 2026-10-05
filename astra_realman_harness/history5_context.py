"""Five completed action/result records; no images, planning, or action changes."""
import copy
from collections import deque

class History5ContextBuilder:
    def __init__(self, base_builder):
        self.base_builder = base_builder
        self.records = deque(maxlen=5)
        self.seen = set()

    def __call__(self, observation, schema):
        context = self.base_builder(observation, schema)
        identity = context["observation_id"]
        if identity not in self.seen:
            previous = context.get("previous")
            if previous is not None:
                if not isinstance(previous, dict) or not {"last_action", "last_result"} <= set(previous):
                    raise ValueError("HISTORY5_INVALID_PREVIOUS")
                self.records.append(copy.deepcopy(previous))
            self.seen.add(identity)
        # Keep every existing field, including previous, intact for compatibility.
        context["history"] = copy.deepcopy(list(self.records))
        return context
