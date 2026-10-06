"""Versioned post-hoc review supplement around an immutable capture snapshot."""
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from io_utils import ROOT, read_json
from evidence_redaction import redact_fields


def reviewed_zip(run):
    from episode_archive import ARCHIVES
    from decision_backends import redact
    run=Path(run).resolve()
    if not run.is_relative_to((ROOT/'logs').resolve()):raise ValueError('REVIEW_SOURCE_PATH')
    receipt=read_json(run/'auto_archive.json')
    capture=Path(receipt.get('path','/')).resolve()
    if receipt.get('status')!='SAVED' or capture.parent!=ARCHIVES.resolve():raise ValueError('ARCHIVE_NOT_SAVED')
    manifest_raw=(capture/'manifest.json').read_bytes()
    anchor=hashlib.sha256(manifest_raw).hexdigest()
    if receipt.get('capture_manifest_sha256') not in (None,anchor):raise ValueError('CAPTURE_MANIFEST_CHANGED')
    manifest=json.loads(manifest_raw);files={'capture/manifest.json':manifest_raw}
    for name,meta in manifest['files'].items():
        path=(capture/name).resolve()
        if not path.is_relative_to(capture) or path.is_symlink():raise ValueError('CAPTURE_FILE_PATH')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256'] or len(raw)!=meta['bytes']:raise ValueError('CAPTURE_FILE_CHANGED:'+name)
        files['capture/'+name]=raw
    episode=json.loads(files['capture/episode.json'])['summary'].get('episode_id',run.name)
    current_episode=read_json(run/'summary.json').get('episode_id',run.name)
    if episode!=current_episode:raise ValueError('CAPTURE_EPISODE_MISMATCH')
    token_path=ROOT/'config/codex_astra_bridge.token'
    secret=token_path.read_text().strip() if token_path.is_file() else ''
    reviews={};associations={}
    paths=[run/'independent_observation.json',*sorted(run.glob('independent-observation-*.json')),*sorted(run.glob('review-marker-*.json'))]
    for path in paths:
        if not path.is_file() or path.is_symlink():continue
        original=path.read_bytes();value=json.loads(original)
        same=value.get('episode_id')==episode
        # Older marker files contain run identity but predate episode_id.
        if path.name.startswith('review-marker-') and 'episode_id' not in value:same=value.get('run')==run.name
        stamp=value.get('recorded_at',value.get('observed_at'))
        valid=bool(same and value.get('observer') and value.get('evidence') and type(stamp) in (int,float))
        associations[path.name]={'episode_matches':same,'review_valid':valid,'observer':value.get('observer'),
                                 'annotation_time':stamp,'original_sha256':hashlib.sha256(original).hexdigest()}
        text=json.dumps(redact_fields(value),ensure_ascii=False,indent=2)
        if secret:text=text.replace(secret,'[REDACTED]')
        text=redact(re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]+',r'\1[REDACTED]',text))
        reviews['review/'+path.name]=text.encode()
    files.update(reviews)
    # Stable version changes only when the captured evidence or review content changes.
    version=hashlib.sha256((anchor+json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in reviews.items()},sort_keys=True)).encode()).hexdigest()
    supplement={'schema_version':1,'review_version':version,'exported_at':time.time(),'episode_id':episode,
                'capture_manifest_sha256':anchor,'capture_anchor_recorded_at_save':bool(receipt.get('capture_manifest_sha256')),
                'post_hoc':True,'model_input':False,'history_input':False,'annotations':redact_fields(associations),
                'files':{n:{'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for n,v in files.items()}}
    # Association strings can contain user-entered credentials too.
    text=json.dumps(supplement,ensure_ascii=False,indent=2)
    if secret:text=text.replace(secret,'[REDACTED]')
    files['review_manifest.json']=redact(text).encode()
    files['index.html']=('''<!doctype html><meta charset="utf-8"><title>Reviewed episode</title>
<h1>整轮证据 · 含事后人工标注</h1><p>capture/ 是结束时原始快照；review/ 是独立版本的事后标注，不进入模型输入或历史。</p>
<p><a href="capture/index.html">查看不可变采集快照</a> · <a href="review_manifest.json">查看版本、观察者、时间和 episode 关联校验</a></p>'''+''.join('<p><a href="'+n+'">'+n+'</a></p>' for n in reviews)).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in files.items():archive.writestr(name,raw)
    return out.getvalue()
