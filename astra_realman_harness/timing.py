"""Monotonic durations with explicit parents. Rows must never be summed across parents."""
import time
from contextlib import contextmanager

class Timings:
    def __init__(self):
        self.rows = []

    @contextmanager
    def measure(self, stage, parent):
        start = time.monotonic()
        try:
            yield
        finally:
            self.rows.append({'stage':stage, 'parent':parent,
                              'duration_s':time.monotonic()-start})
