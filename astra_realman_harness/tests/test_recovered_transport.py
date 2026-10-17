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
