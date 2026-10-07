"""Additive read-only GUI contract; no edits to the existing GUI or capture/export routes."""
def snapshot(state,metrics):
    obj=state.objects.get(state.active_object,{})
    return {'schema':'bimanual-gui-v1','active_object':state.active_object,'class':obj.get('semantic_class'),
       'destination':obj.get('destination'),'holder':obj.get('holder'),'holder_valid':obj.get('holder_valid',True),
       'phase':state.phase,'left_status':state.arms['left'],'right_status':state.arms['right'],'handoff_status':state.handoff,
       'astra_call_count':sum(x['astra_calls'] for x in metrics.values()),'object_elapsed_time_s':metrics.get(state.active_object,{}).get('seconds_per_object'),
       'source':'SYNTHETIC_ONLY','requested_effort':'medium','hardware_enabled':False}
