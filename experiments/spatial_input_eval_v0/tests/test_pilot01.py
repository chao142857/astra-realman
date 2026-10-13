"""Offline budget/stop-rule tests. Never use a real HTTP service or CLI process."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'lab'))
import pilot01 as p


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history_job = dict(scene_id=p.SCENES[4], task_id='plan', condition=p.A)
        self.seal = dict(model_parameters=p.PARAMETERS, file_sha256={},
            payload_sha256={p.key(self.history_job):p.digest(p.read(p.HISTORY/'sample-0000/request.json'))},
            normalized_command=p.normalized_command(p.read(p.HISTORY/'sample-0000/bridge_result.json')))

    def copy_run(self):
        run = self.root/'run'
        (run/'sample-0000').mkdir(parents=True)
        shutil.copy2(p.HISTORY/'results.json', run/'results.json')
        for name in ('transport.json', 'response.json', 'bridge_result.json', 'model_parameters.json', 'request.json'):
            shutil.copy2(p.HISTORY/'sample-0000'/name, run/'sample-0000'/name)
        return run

    def state(self, reservations=None, status='READY'):
        value = dict(status=status, max_new_dispatches=24, jobs=p.schedule(), reservations=reservations or [])
        p.save(self.root/'ledger.json', value); p.save(self.root/'frozen_preflight.json', self.seal)
        return value

    def test_order_budget_and_repeat(self):
        jobs = p.schedule()
        self.assertEqual(len(jobs), 24)
        self.assertEqual([(j['scene_id'],j['task_id'],j['condition']) for j in jobs[:3]],
            [(p.SCENES[4],'plan',p.C),(p.SCENES[5],'plan',p.A),(p.SCENES[5],'plan',p.C)])
        self.assertEqual(jobs[-1]['role'], 'independent_repeat')
        primary = {p.key(j) for j in jobs[:-1]} | {p.key(self.history_job)}
        self.assertEqual(len(primary), 24)
        self.assertEqual(sum(j['role']=='independent_repeat' for j in jobs), 1)

    def test_historical_completed_result_passes(self):
        audit = p.inspect_result(p.HISTORY, self.history_job, self.seal)
        self.assertEqual(audit['status'], 'VALID')
        self.assertEqual(audit['score'], 1)

    def test_missing_completed_event_stops(self):
        run = self.copy_run(); file = run/'sample-0000/response.json'; response = p.read(file)
        response['events'] = '\n'.join(line for line in response['events'].splitlines() if 'turn.completed' not in line)
        p.save(file, response)
        with self.assertRaisesRegex(ValueError, 'TURN_COMPLETED'):
            p.inspect_result(run, self.history_job, self.seal)

    def test_code_mode_or_model_drift_stops(self):
        run = self.copy_run(); file = run/'sample-0000/bridge_result.json'; value = p.read(file)
        value['command'].remove('code_mode_host'); p.save(file, value)
        with self.assertRaisesRegex(ValueError, 'CODE_MODE_DRIFT'):
            p.inspect_result(run, self.history_job, self.seal)

    def test_invalid_json_transport_timeout_and_auth_stop(self):
        for kind in ('json', 'timeout', '403', '409', 'empty'):
            with self.subTest(kind=kind):
                run = self.copy_run() if not (self.root/'run').exists() else self.root/'run'
                # Restore the altered files for independent fault injection.
                for name in ('response.json', 'transport.json'):
                    shutil.copy2(p.HISTORY/'sample-0000'/name, run/'sample-0000'/name)
                shutil.copy2(p.HISTORY/'results.json', run/'results.json')
                if kind in ('403', '409', 'timeout'):
                    file = run/'sample-0000/transport.json'; value = p.read(file)
                    value['http_status'] = int(kind) if kind != 'timeout' else None
                elif kind == 'json':
                    file = run/'results.json'; value = p.read(file); value[0]['parse_status']='INVALID'
                else:
                    file = run/'sample-0000/response.json'; value = p.read(file); value['raw']=''
                p.save(file, value)
                with self.assertRaises(ValueError):
                    p.inspect_result(run, self.history_job, self.seal)

    def test_valid_geometry_failure_is_a_valid_sample(self):
        run = self.copy_run(); response = p.read(run/'sample-0000/response.json')
        response['raw'] = json.dumps(dict(object_id='target',position_m=[2,2,2],quaternion_wxyz=[1,0,0,0],waypoints_m=[]))
        p.save(run/'sample-0000/response.json', response)
        s = p.load_snapshot(p.SUITE/p.SCENES[4]/'snapshot.json'); task = next(t for t in s['task'] if t['task_id']=='plan')
        rows = p.read(run/'results.json'); rows[0].update(p.cli.assess_response(response,s,task)); p.save(run/'results.json',rows)
        audit = p.inspect_result(run, self.history_job, self.seal)
        self.assertEqual((audit['status'], audit['score']), ('VALID', 0))

    def test_budget_stopped_and_crash_guards_never_dispatch(self):
        for state, reservations in [('STOPPED', []), ('COMPLETE', []),
                                     ('READY', [dict(status='IN_FLIGHT')]),
                                     ('READY', [dict(status='VALID')]*24)]:
            self.state(reservations, state)
            with patch.object(p.cli, 'run') as dispatch:
                with self.assertRaises(ValueError):
                    p.next_request(self.root)
                dispatch.assert_not_called()

    def test_reservation_is_durable_before_dispatch_and_failure_never_retries(self):
        self.state()
        connection = unittest.mock.MagicMock()
        connection.getresponse.return_value.status = 501
        job = p.schedule()[0]; self.seal['payload_sha256'][p.key(job)] = p.digest({})
        p.save(self.root/'frozen_preflight.json', self.seal)
        def fail(*args, **kwargs):
            state = p.read(self.root/'ledger.json')
            self.assertEqual(len(state['reservations']), 1)
            self.assertEqual(state['reservations'][0]['status'], 'IN_FLIGHT')
            self.assertEqual(kwargs['max_real_calls'], 1)
            self.assertEqual(kwargs['timing_mode'], 'qualification')
            raise TimeoutError('simulated')
        with patch.object(p.http.client,'HTTPConnection',return_value=connection), \
             patch.object(p,'payload_for',return_value=({},{})), \
             patch.object(p,'summarize',return_value={'completed_pairs':0}), \
             patch.object(p.cli,'run',side_effect=fail) as dispatch:
            self.assertEqual(p.next_request(self.root), 2)
            with self.assertRaises(ValueError): p.next_request(self.root)
            self.assertEqual(dispatch.call_count,1)
        self.assertEqual(p.read(self.root/'ledger.json')['status'], 'STOPPED')

    def test_changed_frozen_input_prevents_dispatch(self):
        file=self.root/'frozen.txt'; file.write_text('a')
        seal=copy.deepcopy(self.seal); seal['file_sha256']={str(file):p.sha(file)}; file.write_text('b')
        with self.assertRaisesRegex(ValueError,'FROZEN_FILE_CHANGED'): p.verify_seal(seal)

    def test_global_lock_blocks_parallel_runner(self):
        with p.locked(self.root):
            with self.assertRaisesRegex(ValueError, 'ANOTHER_PILOT_RUNNER_ACTIVE'):
                with p.locked(self.root): pass


if __name__=='__main__': unittest.main()
