"""Automatic end-of-episode archive. Observation only; never changes robot/model policy."""
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from io_utils import ROOT, read_json

ARCHIVES=ROOT/'logs/episodes'
SHANGHAI=timezone(timedelta(hours=8),'Asia/Shanghai')


def task_filename(task):
    text=re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', task)
    text=re.sub(r'\s+',' ',text).strip(' ._') or '未命名任务'
    # UTF-8 byte limit, not character count: safe on common Linux/macOS filesystems.
    text=text.encode('utf-8')[:120].decode('utf-8','ignore').rstrip(' ._')
    if text.upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:text='任务_'+text
    return text


def atomic_json(path,value):
    temp=path.with_name('.'+path.name+'-'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temp,path)


def archive_episode(run,task):
    run=Path(run).resolve()
    if not run.is_relative_to((ROOT/'logs').resolve()) or run.is_relative_to(ARCHIVES.resolve()):raise ValueError('ARCHIVE_SOURCE_PATH')
    if not isinstance(task,str):raise ValueError('ARCHIVE_TASK')
    if not (run/'summary.json').is_file():raise ValueError('EPISODE_NOT_FINALIZED')
    ARCHIVES.mkdir(parents=True,exist_ok=True)
    with (run/'.auto_archive.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        receipt=run/'auto_archive.json'
        if receipt.is_file():
            old=read_json(receipt);saved=Path(old.get('path','/')).resolve()
            if old.get('status')=='SAVED' and saved.parent==ARCHIVES.resolve() and (saved/'manifest.json').is_file():return old
        stamp=datetime.now(SHANGHAI)
        name=task_filename(task)+'__'+stamp.strftime('%Y%m%d_%H%M%S_%f')+'_CST'
        destination=ARCHIVES/name
        while destination.exists():destination=ARCHIVES/(name+'_'+uuid.uuid4().hex[:6])
        staging=ARCHIVES/('.partial-'+uuid.uuid4().hex);staging.mkdir()
        try:
            result=_build_archive(run,task,staging,stamp)
            staging.rename(destination)
            result.update(status='SAVED',path=str(destination),index=str(destination/'index.html'),
                          capture_manifest_sha256=hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest())
            atomic_json(receipt,result)
            return result
        except BaseException:
            # Only our unpublished staging directory is removed. Source evidence stays intact.
            shutil.rmtree(staging,ignore_errors=True)
            raise


def _build_archive(run,task,output,stamp):
    from decision_backends import redact
    warnings=[];copied={};images={};documents={}
    token_path=ROOT/'config/codex_astra_bridge.token'
    token=token_path.read_text().strip() if token_path.is_file() else ''
    def clean(text):
        if token:text=text.replace(token,'[REDACTED]')
        return redact(re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]+',r'\1[REDACTED]',text))
    def save(relative,data):
        path=output/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        copied[relative]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    def picture(value,expected=None):
        path=Path(value).resolve()
        if not path.is_relative_to((ROOT/'logs').resolve()) or not path.is_file():
            warnings.append('MISSING_OR_OUTSIDE_IMAGE: '+str(value));return None
        if path.stat().st_size>8*1024*1024:
            warnings.append('IMAGE_TOO_LARGE: '+str(value));return None
        if str(path) in images:
            relative=images[str(path)]
            if expected and expected!=Path(relative).stem:warnings.append('IMAGE_HASH_MISMATCH: '+str(value))
            return relative
        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            warnings.append('INVALID_PNG: '+str(value));return None
        if expected and expected!=digest:warnings.append('IMAGE_HASH_MISMATCH: '+str(value))
        relative='images/'+digest+'.png'
        if relative not in copied:save(relative,data)
        images[str(path)]=relative
        return relative
    def portable(value,key=''):
        from evidence_redaction import sensitive_key,statistic,STATS,STAT_OBJECTS
        if sensitive_key(key):return '[REDACTED]'
        if key in STATS|STAT_OBJECTS:return statistic(key,value)
        if isinstance(value,dict):
            result={k:portable(v,k) for k,v in value.items() if k!='image_path'}
            if 'image_path' in value:result['image_path']=picture(value['image_path'],value.get('sha256')) or 'MISSING_IMAGE'
            return result
        if isinstance(value,list):return [portable(v,key) for v in value]
        if not isinstance(value,str):return value
        # Task is preserved exactly; file references elsewhere become portable.
        if key=='task':return value
        if value.startswith(str(run)+os.sep):return 'record/'+str(Path(value).relative_to(run))
        return clean(value)
    for source in sorted(run.rglob('*')):
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(run):continue
        rel=source.relative_to(run)
        if any(p.startswith('.') for p in rel.parts) or source.name=='auto_archive.json':continue
        if source.suffix.lower() not in ('.json','.jsonl','.txt','.log','.png'):continue
        target='record/'+rel.as_posix()
        try:
            if source.suffix.lower()=='.png':
                picture(str(source));continue
            if source.suffix=='.json' or source.name=='prompt.txt':
                try:
                    value=read_json(source);value=portable(value);documents[rel.as_posix()]=value
                    save(target,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode())
                    continue
                except (ValueError,UnicodeError) as exc:
                    warnings.append('UNPARSED_RECORD: '+rel.as_posix()+': '+type(exc).__name__)
            save(target,clean(source.read_text(encoding='utf-8')).encode())
        except (OSError,ValueError,UnicodeError,TypeError) as exc:
            warnings.append('COPY_ERROR: '+rel.as_posix()+': '+type(exc).__name__+': '+str(exc))
    # GUI terminal log lives in its session directory. Never copy arbitrary linked files.
    launch=documents.get('gui_launch.json',{})
    console=Path(launch.get('console_log','/')).resolve()
    if console.is_relative_to((ROOT/'logs').resolve()) and console.is_file():
        try:save('console.log',clean(console.read_text(encoding='utf-8')).encode())
        except (OSError,UnicodeError) as exc:warnings.append('CONSOLE_COPY_ERROR: '+str(exc))
    save('task.txt',task.encode('utf-8'))
    summary=documents.get('summary.json',{})
    steps=[]
    def esc(value):return html.escape(str(value),quote=True)
    sections=[]
    for folder in sorted(run.glob('step-*')):
        if not folder.is_dir():continue
        name=folder.name;prefix=name+'/'
        from replay_evidence import request_image_evidence
        request=request_image_evidence(run,name)
        source=request['source']
        attachments=[]
        for item in request['images']:
            item=dict(item)
            item['image_path']=picture(item['image_path'],item['expected_hash']) if item.get('image_path') else None
            attachments.append(item)
            if not item['available']:warnings.append('INVALID_MODEL_INPUT: '+name+': '+str(item.get('serial'))+': '+','.join(item['errors']))
        diagnostics=documents.get(prefix+'diagnostics.json')
        action=documents.get(prefix+'parsed_action.json')
        execution=documents.get(prefix+'execution_result.json')
        transition=documents.get(prefix+'transition.json')
        row={'step':name,'image_evidence':source,'input_images':[c for c in attachments if c['available']],
             'invalid_input_images':[c for c in attachments if not c['available']],
             'input_image_evidence':attachments,'diagnostics':diagnostics,
             'proposed_action':action,'execution':execution,'transition':transition}
        steps.append(row)
        figures=[]
        for i,c in enumerate(attachments or [],1):
            path=c.get('image_path');label=f"{i:02d} · {c.get('role','unknown')} · {c.get('serial','unknown')}"
            image=f'<a href="{esc(path)}"><img src="{esc(path)}" alt="{esc(label)}"></a>' if c['available'] and path in copied else '<p><strong>INVALID · 不可作为有效模型输入图</strong><br>'+esc(', '.join(c['errors']))+'</p>'+ (f'<a href="{esc(path)}">损坏 / 引用无效的调查文件</a>' if path in copied else '<p>图片缺失</p>')
            figures.append('<figure>'+image+'<figcaption>'+esc(label)+'</figcaption></figure>')
        def show(value,empty):return esc(json.dumps(value,ensure_ascii=False,indent=2)) if value is not None else empty
        raw_paths=[prefix+'raw_proposal.txt',prefix+'decision/astra_raw.txt']
        raw_links=' '.join(f'<a href="record/{esc(p)}">{esc(Path(p).name)}</a>' for p in raw_paths if 'record/'+p in copied)
        sections.append(f'<section><h2>{esc(name)}</h2><p>{esc(source)}</p><div class="photos">'+''.join(figures)+
            '</div><h3>公开诊断 / 推理摘要</h3><pre>'+show(diagnostics,'该步没有公开诊断；D0 不输出诊断，未输出内容不补写。')+
            '</pre><h3>动作决策（原值）</h3><pre>'+show(action,'该步未得到有效动作决策；查看原始输出。')+
            '</pre><details><summary>实际执行与实测反馈</summary><pre>'+show(transition or execution,'没有执行记录。')+
            '</pre></details><p>'+raw_links+'</p></section>')
    fixture=any(isinstance(v,dict) and v.get('backend')=='OFFLINE_FIXTURE_NOT_ASTRA' for k,v in documents.items() if k.endswith('backend_result.json'))
    details={'offline_fixture':fixture,'task':task,'source_run':str(run),'archived_at':stamp.isoformat(),'timezone':'Asia/Shanghai',
             'summary':summary,'synthetic':(run/'SYNTHETIC.json').is_file(),'steps':steps,
             'notes':'End-of-episode snapshot. Public model output only; no fabricated internal reasoning. Post-hoc labels are available only in the separate reviewed export.'}
    save('episode.json',json.dumps(details,ensure_ascii=False,indent=2).encode())
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>整轮实验归档</title><style>body{font:15px system-ui;background:#121b20;color:#e1e9e6;max-width:1200px;margin:40px auto;padding:0 24px}h1{white-space:pre-wrap;overflow-wrap:anywhere}section{background:#1d292f;padding:24px;margin:24px 0;border-radius:16px}.photos{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}figure{margin:0}img{width:100%;max-height:320px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}a{color:#b6ddc8}figcaption{color:#a5b7bf;margin-top:8px}</style>'''
    page+='<h1>'+esc(task)+'</h1><p>'+esc(stamp.strftime('%Y-%m-%d %H:%M:%S')+' Asia/Shanghai')+'</p><p>'+('SYNTHETIC · 合成数据，非真实实验' if details['synthetic'] else 'OFFLINE FIXTURE · 固定测试响应，非真实模型推理' if fixture else '实验结束时自动保存')+'</p><p>回合状态：'+esc(summary.get('status','unknown'))+'；模型 done / SDK 成功不自动代表物体任务成功。</p><p><a href="task.txt">原始任务</a> · <a href="episode.json">整轮结构化记录</a> · <a href="manifest.json">文件校验清单</a></p>'+''.join(sections)
    if warnings:page+='<h2>归档缺项 / 校验提示</h2><pre>'+esc('\n'.join(warnings))+'</pre>'
    save('index.html',page.encode())
    result={'task':task,'archived_at':stamp.isoformat(),'timezone':'Asia/Shanghai','steps':len(steps),'image_count':len(set(images.values())),
            'warnings':warnings,'source_run':str(run),'synthetic':details['synthetic'],'offline_fixture':fixture,
            'valid_input_image_count':sum(len(s['input_images']) for s in steps),
            'invalid_input_image_count':sum(len(s['invalid_input_images']) for s in steps),
            'evidence_status':'INVALID_INPUTS' if any(s['invalid_input_images'] for s in steps) else 'VALID_RECORDED_INPUTS' if any(s['input_images'] for s in steps) else 'NO_INPUT_IMAGES'}
    save('manifest.json',json.dumps(dict(result,files=dict(copied),path_base='archive root'),ensure_ascii=False,indent=2).encode())
    return result


def finalize_archive(run,task,emit):
    """Best effort after final summary; failures never hide the experiment result or original logs."""
    try:
        result=archive_episode(run,task)
    except Exception as exc:
        result={'status':'FAILED','error':type(exc).__name__+': '+str(exc),'source_run':str(run)}
        try:atomic_json(Path(run)/'auto_archive.json',result)
        except OSError:pass
    emit('AUTO ARCHIVE',result)
    return result
