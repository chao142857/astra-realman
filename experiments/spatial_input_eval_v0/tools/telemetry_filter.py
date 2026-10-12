"""Allowlist OTLP phase metadata. Never persist raw OTLP, bodies, headers or IDs."""
import math

EVENTS = {'codex.api_request','codex.websocket_connect','codex.websocket_request','codex.sse_event'}
SPANS = {'model_client.stream_responses_api','model_client.stream_responses_websocket',
         'responses.stream_request','responses.stream','responses_websocket.connect',
         'endpoint_session.stream_encoded_json_with','startup_prewarm_websocket_warmup'}
METRICS = {'codex.api_request','codex.api_request.duration_ms','codex.sse_event',
           'codex.sse_event.duration_ms','codex.websocket.event','codex.websocket.event.duration_ms',
           'codex.websocket.request','codex.websocket.request.duration_ms'}
KINDS = {'response.created','response.in_progress','response.output_item.added',
         'response.output_item.done','response.output_text.delta','response.completed',
         'response.incomplete','response.failed','response.reasoning_text.delta',
         'response.reasoning_summary_text.delta','ping','pong','parse_error','unknown'}
CONTAINERS = ('resourceLogs','scopeLogs','resourceSpans','scopeSpans','resourceMetrics','scopeMetrics')


def scalar(value):
    if not isinstance(value,dict): return None
    for k in ('stringValue','intValue','doubleValue','boolValue'):
        if k in value: return value[k]
    return None


def attributes(items):
    result={}
    for item in items or []:
        key=item.get('key'); value=scalar(item.get('value'))
        if key=='event.name' and value in EVENTS: result[key]=value
        elif key in ('event.kind','kind') and value in KINDS: result[key]=value
        elif key in ('success','auth.header_attached') and value in (True,False,'true','false'):
            result[key]=value
        elif key in ('duration_ms','http.response.status_code','attempt'):
            try: number=float(value)
            except (ValueError,TypeError): continue
            if math.isfinite(number) and 0<=number<=1e9: result[key]=number
    return result


def phases(payload):
    """OTLP HTTP JSON logs, traces and metrics, with no resource identity retention."""
    result=[]
    def visit(node):
        if not isinstance(node,dict): return
        for entry in node.get('logRecords',[]):
            attrs=attributes(entry.get('attributes'))
            if attrs.get('event.name') in EVENTS:
                result.append({'type':'event','attributes':attrs})
        for entry in node.get('spans',[]):
            if entry.get('name') in SPANS:
                result.append({'type':'span','name':entry['name'],'attributes':attributes(entry.get('attributes'))})
        for entry in node.get('metrics',[]):
            if entry.get('name') not in METRICS: continue
            for kind in ('sum','histogram','gauge'):
                for point in entry.get(kind,{}).get('dataPoints',[]):
                    record={'type':'metric','name':entry['name'],'attributes':attributes(point.get('attributes'))}
                    for field in ('asInt','asDouble','count','sum'):
                        if field in point:
                            try: val=float(point[field])
                            except (ValueError,TypeError): continue
                            if math.isfinite(val) and 0<=val<=1e15: record[field]=val
                    result.append(record)
        for key in CONTAINERS:
            for child in node.get(key,[]): visit(child)
    visit(payload)
    return result
