import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recovered_transport import check_recovered_events
from decision_backends import check_events,BackendFailure
class Recovery(unittest.TestCase):
    def events(self):return [{'type':'thread.started'},{'type':'turn.started'},{'type':'error','message':'Reconnecting... 2/5 (stream disconnected before completion: tls handshake eof)'},{'type':'item.completed','item':{'type':'error','message':'Falling back from WebSockets to HTTPS transport. stream disconnected before completion: tls handshake eof'}},{'type':'item.completed','item':{'type':'agent_message','text':'{}'}},{'type':'turn.completed'}]
    def encode(self,e):return '\n'.join(map(json.dumps,e))
    def test_recovered_and_old_policy_unchanged(self):
        text=self.encode(self.events());self.assertEqual(check_recovered_events(text)[0],'{}')
        self.assertEqual(len(check_recovered_events(text)[1]),2)
        with self.assertRaises(BackendFailure):check_events(text)
    def test_fail_closed(self):
        base=self.events()
        cases=[base[:-1],base+[base[-1]],base[:4]+[base[4]]+base[4:],base+[{'type':'error','message':'anything'}],base[:2]+[{'type':'turn.failed'}]+base[2:]]
        changed=self.events();changed[2]['message']='authentication failed';cases.append(changed)
        for c in cases:
            with self.subTest(c=c),self.assertRaises(BackendFailure):check_recovered_events(self.encode(c))

    def test_new_exact_recovery_notices(self):
        from recovered_transport import RECOVERABLE_REASONS
        for reason in RECOVERABLE_REASONS:
            e=self.events();e[2]['message']='Reconnecting... 2/5 ('+reason+')'
            with self.subTest(reason=reason):
                self.assertEqual(check_recovered_events(self.encode(e))[0],'{}')
                with self.assertRaises(BackendFailure):check_events(self.encode(e))

    def test_recovery_does_not_hide_failure_or_late_errors(self):
        from recovered_transport import RECOVERABLE_REASONS
        for reason in RECOVERABLE_REASONS:
            e=self.events();e[2]['message']='Reconnecting... 2/5 ('+reason+')'
            cases=[e[:-1], e[:4]+[{'type':'turn.failed'}]+e[4:],
                   e[:4]+[e[4]]+e[4:], e[:2]+e[3:5]+[e[2]]+e[5:]]
            for case in cases:
                with self.subTest(reason=reason,case=case),self.assertRaises(BackendFailure):
                    check_recovered_events(self.encode(case))

    def test_unknown_reconnect_reason_rejected(self):
        for reason in ['HTTP 403','request timed out','workspace routing discovery failed: unauthorized',
                       'stream disconnected before completion: Connection reset by peer (os error 99)']:
            e=self.events();e[2]['message']='Reconnecting... 2/5 ('+reason+')'
            with self.subTest(reason=reason),self.assertRaises(BackendFailure):
                check_recovered_events(self.encode(e))
