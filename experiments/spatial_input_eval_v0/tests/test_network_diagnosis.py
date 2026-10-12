"""No sockets, credentials, CLI, or model invocation in these regression tests."""
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'diagnostics/diagnose_network.py'
spec=importlib.util.spec_from_file_location('diagnose_network',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
catalog_spec=importlib.util.spec_from_file_location('cli_network_probe',path.with_name('cli_network_probe.py'))
catalog_module=importlib.util.module_from_spec(catalog_spec);catalog_spec.loader.exec_module(catalog_module)


def report(filtered,proxy):
    def case(name,ready):
        return {'name':name,'result':{'probes':[{'kind':'https_get_no_auth','status':'HTTP_RESPONSE' if ready else 'FAIL','http_status':401 if ready else None}]*2}}
    return {'cases':[case('worker_filtered',filtered),case('worker_https_proxy_candidate',proxy)]}

class NetworkDiagnosisTests(unittest.TestCase):
    def test_outer_denial_not_misclassified_as_proxy(self):
        r=module.classify(report(False,False),report(True,True))
        self.assertEqual(r['status'],'OUTER_EXECUTION_NETWORK_BOUNDARY_CONFIRMED')
        self.assertFalse(r['production_proxy_allowlist_change_required'])
    def test_proxy_only_when_candidate_restores_host_worker(self):
        r=module.classify(report(False,False),report(False,True))
        self.assertEqual(r['status'],'HTTPS_PROXY_FORWARDING_NECESSARY_IN_TESTED_HOST')
        self.assertTrue(r['production_proxy_allowlist_change_required'])
    def test_healthy_network_requires_routing_auth_diagnosis(self):
        self.assertEqual(module.classify(report(True,True),report(True,True))['status'],
                         'NETWORK_TRANSPORT_READY_ROUTING_AND_AUTH_REQUIRE_SEPARATE_CHECK')
    def test_bundled_catalog_is_not_service_evidence(self):
        self.assertFalse(module.catalog_has_remote_evidence({'return_code':0,'same_as_bundled':True,'refresh_error_logged':False}))
        self.assertFalse(module.catalog_has_remote_evidence({'return_code':0,'refresh_error_logged':False}))
        self.assertTrue(module.catalog_has_remote_evidence({'return_code':0,'same_as_bundled':False,'refresh_error_logged':False}))
    def test_invalid_cli_catalog_does_not_crash_or_prove_connectivity(self):
        for stdout,bundled in (('', '{}'), ('{"models": [null]}', '{}'), ('{"models": []}', 'broken')):
            result=catalog_module.catalog_metadata(stdout,'',bundled)
            self.assertEqual(result['catalog_parse'],'INVALID')
            self.assertFalse(module.catalog_has_remote_evidence({'return_code':0,**result}))

if __name__=='__main__':unittest.main()
