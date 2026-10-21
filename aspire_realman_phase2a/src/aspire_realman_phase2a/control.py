"""Native session operation_controller for the exact offline Stub only."""
import threading
from cap_harness.errors import ApiError,ErrorCode

class StubOperationController:
    def __init__(self,engine):
        self.engine=engine;self.lock=threading.RLock();self.active=False;self.events=[]
    def begin_operation(self,*,kind,label):
        with self.lock:
            if self.engine.transport.cancel_event.is_set():raise ApiError(ErrorCode.CANCELLED,'SESSION_STUB_ABORT_LATCHED_NO_AUTO_RESET')
            self.active=True;self.events.append({'event':'begin','kind':kind,'label':label})
    def end_operation(self,*,kind,label):
        with self.lock:
            self.active=False;self.events.append({'event':'end','kind':kind,'label':label})
    def cancel_operation(self):
        with self.lock:
            result=self.engine.abort()
            receipt={'event':'cancel','stub_ticks_at_ack':len(self.engine.transport.events),**result}
            self.events.append(receipt);return receipt
    def close(self):self.cancel_operation()
