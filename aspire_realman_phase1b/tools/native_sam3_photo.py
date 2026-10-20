"""Unchanged native SAM3 HTTP service/client on the SAME sealed RGB.
No RobotState or full CAP Observation is constructed. No hardware transport.
"""
import base64,hashlib,io,time
from pathlib import Path
import numpy as np
from PIL import Image
import requests
from rgbd_evidence import artifact
from sam3_results import classify,save_predictions


def native_camera(rgb,z,meta):
    from cap_harness.contracts import CameraObservation,Pose
    frame=meta['optical_frame']
    # Exact self-frame identity only, not a guessed camera->World transform.
    return CameraObservation(rgb=rgb,depth_m=z,intrinsics=np.array(meta['intrinsics']),frame=frame,
        camera_pose=Pose(position=np.zeros(3),quaternion_wxyz=[1,0,0,0],frame=frame),timestamp_s=meta['captured_at'])


def probe_native(model,processor,rgb,z,meta,out,prompt,threshold):
    from cap_harness.providers.sam3 import service
    from cap_harness.providers.sam3.client import Sam3Provider
    from http_support import loopback_server
    from rgbd_evidence import sha
    native_sha=sha(service.__file__)
    if native_sha!='2b92c1a964e197d40bb653ac8725086d64cbbcd155913ae17bb9b81def605920':
        raise RuntimeError('NATIVE_SAM3_SERVICE_HASH_MISMATCH')
    original_decode=service._decode_image;incoming=[];requests_trace=[]
    def trace_decode(payload):
        image=original_decode(payload)
        incoming.append({'encoded_png_sha256':hashlib.sha256(base64.b64decode(payload)).hexdigest(),
            'decoded_rgb_pixel_sha256':hashlib.sha256(np.array(image).tobytes()).hexdigest()})
        return image
    service._decode_image=trace_decode
    service._MODEL=model;service._PROCESSOR=processor;service._DEVICE='cuda'
    class TracingSession(requests.Session):
        def request(self,method,url,**kwargs):
            row={'method':method,'path':url.split('/',3)[-1]}
            body=kwargs.get('json')
            if body and 'image_base64' in body:
                encoded=base64.b64decode(body['image_base64'])
                row.update(encoded_png_sha256=hashlib.sha256(encoded).hexdigest(),
                    decoded_rgb_pixel_sha256=hashlib.sha256(np.array(Image.open(io.BytesIO(encoded)).convert('RGB')).tobytes()).hexdigest())
            started=time.perf_counter();response=super().request(method,url,**kwargs)
            row.update(http_status=response.status_code,elapsed_s=time.perf_counter()-started)
            if response.status_code!=200:row['error_body']=response.json()
            requests_trace.append(row)
            return response
    session=TracingSession();session.trust_env=False
    result={'scope':'native ASPIRE service + typed Sam3Provider over actual loopback HTTP',
        'native_service_sha256':native_sha,'model_initialized':model is not None,'calls':[],
        'world_transform':None,'full_cap_observation_constructed':False,
        'peak_vram_allocated_bytes':None,'peak_vram_reserved_bytes':None}
    if model is not None and service.torch.cuda.is_available():
        service.torch.cuda.reset_peak_memory_stats()
    try:
        with loopback_server(service.app) as base:
            provider=Sam3Provider(base_url=base,session=session,timeout_s=120,max_retries=0)
            result['process_health']=provider.health()
            camera=native_camera(rgb,z,meta)
            calls=3 if model is not None else 1
            for i in range(calls):
                started=time.perf_counter();seg=provider.segment_text(camera,prompt)
                row={'ok':seg.ok,'elapsed_s':time.perf_counter()-started,
                     'error':None if seg.error is None else {'code':seg.error.code.value,'message':seg.error.message,'details':dict(seg.error.details)}}
                if seg.ok:
                    row.update(save_predictions(np.stack([s.mask for s in seg.segmentations]) if seg.segmentations else np.empty((0,*z.shape),bool),
                        np.stack([s.box_xyxy for s in seg.segmentations]) if seg.segmentations else np.empty((0,4)),[s.score for s in seg.segmentations],
                        rgb,z,meta,out,f'native-run{i+1}',threshold,geometry=i==calls-1))
                elif seg.error.code.value=='no_segmentation':
                    # Native client converts an actual empty model result into a typed
                    # failure. Record completion without claiming a target or overlay.
                    row.update(classify(0,0),predictions=[],overlay=None)
                result['calls'].append(row)
            # Actual native client's empty-query refusal does not reach a model.
            before=len(requests_trace);invalid=provider.segment_text(camera,'')
            result['empty_prompt_error']={'ok':invalid.ok,'code':invalid.error.code.value,'http_requests_sent':len(requests_trace)-before}
    finally:
        session.close();service._decode_image=original_decode;service._MODEL=None;service._PROCESSOR=None
        if model is not None and service.torch.cuda.is_available():
            result['peak_vram_allocated_bytes']=service.torch.cuda.max_memory_allocated()
            result['peak_vram_reserved_bytes']=service.torch.cuda.max_memory_reserved()
    pixel_sha=hashlib.sha256(rgb.tobytes()).hexdigest()
    result.update(request_trace=requests_trace,server_decoded_inputs=incoming,
        expected_rgb_pixel_sha256=pixel_sha,
        outgoing_pixel_identity_verified=all(r['decoded_rgb_pixel_sha256']==pixel_sha for r in requests_trace if 'decoded_rgb_pixel_sha256' in r),
        server_pixel_identity_verified=bool(incoming) and all(r['decoded_rgb_pixel_sha256']==pixel_sha for r in incoming),
        file_png_sha_note='Native client re-encodes PNG, so encoded-file SHA may differ; decoded RGB pixel hash must agree.',
        status='BLOCKED_CHECKPOINT_MODEL_UNINITIALIZED' if model is None else 'NATIVE_INFERENCE_ATTEMPTED')
    return result
