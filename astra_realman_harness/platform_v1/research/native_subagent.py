"""Separate optional provider gate. Never aliases direct CLI or Python concurrency."""
class NativeCodexSubagentBackend:
    name = 'native_codex_subagent'
    @staticmethod
    def capabilities():
        return {'backend': NativeCodexSubagentBackend.name, 'status': 'UNVERIFIED_DISABLED',
            'reason': 'REAL_PARENT_CHILD_IMAGE_USAGE_ACCEPTANCE_REQUIRED',
            'required_evidence': ['actual_parent_and_child_ids', 'child_received_image_hashes_and_schema',
                'parent_child_raw_events', 'per_call_usage_raw_or_null', 'cancellation_and_deadlines',
                'observed_overlap_intervals_not_coroutines'],
            'real_requests_authorized_this_increment': 0}
    def submit(self, *_args, **_kwargs):
        raise ValueError('NATIVE_SUBAGENT_NOT_ACCEPTED')
