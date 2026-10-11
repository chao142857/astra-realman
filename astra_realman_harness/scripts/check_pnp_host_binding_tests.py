"""Explicit narrow suite; skipped cases are not acceptance."""
import unittest,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_pnp_host_binding import HostBindingTests
from test_full_pnp_connection import PnPTests
from test_postcontact_recovery import RecoveryBrokerTests
out=Path('/home/alex/astra-realman_ws/pnp-host-binding-20261010');suite=unittest.TestSuite()
for name in HostBindingTests.__dict__:
 if name.startswith('test_'):suite.addTest(HostBindingTests(name))
for name in ['test_pnp_coarse_broker_preserves_four_actions','test_pnp_fine_small_move_and_close_boundary','test_pnp_postgripper_future_rejected','test_pnp_null_decisions','test_pnp_host_override_rejected','test_pnp_schema','test_pnp_stale_epoch_rejected','test_pnp_auth_required','test_first_step_measured_origin_enforced','test_reasonable_stage_terminal_and_boundary_conflicts']:suite.addTest(PnPTests(name))
for name in ['test_planned_uses_trusted_host_semantic_without_echo','test_noaction_missing_semantic_echo_allowed_nonexecuting','test_noaction_new_claim_without_evidence_still_rejected','test_recovery_cannot_enter_supervisor_or_owner','test_noaction_episode_world_and_readversions_tamper_rejected']:suite.addTest(RecoveryBrokerTests(name))
start=time.monotonic()
with (out/'TESTS_full.log').open('x') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
summary={'run':r.testsRun,'passed':r.testsRun-len(r.skipped)-len(r.failures)-len(r.errors),'skipped':r.skipped,'failures':[(str(t),s) for t,s in r.failures],'errors':[(str(t),s) for t,s in r.errors],'wall_s':time.monotonic()-start,'real_models':0,'episodes':0};(out/'TESTS_full.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary));raise SystemExit(not r.wasSuccessful() or bool(r.skipped))
