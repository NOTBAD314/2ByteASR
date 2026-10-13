"""Conservative, read-only recognition of documented producer contracts.

Recognition offers an explicit adoption step; it never authorizes deletion by
extension or a directory name alone. Legacy consumers lacking leases block adoption.
"""
import json
import os
from pathlib import Path
import re
import time
import sys


def legacy_consumers():
    import psutil
    found=[]
    # Querying every system process' cmdline can block for minutes on Windows.
    # Birth times only gate ambiguous recent slots, never the whole category.
    for process in psutil.process_iter(['pid','name']):
        if process.pid==os.getpid():continue
        try:
            name=(process.info.get('name') or '').lower()
            python_app=False
            if name.startswith('python'):
                command=' '.join(process.cmdline()).lower()
                python_app='quick_start.py' in command or '-m twobyteasr' in command
            if name in {'mpv.exe','2byteasr.exe'} or python_app:
                found.append(process.pid)
        except psutil.Error:continue
    return found


def candidates(paths, files):
    from .storage_service import CacheItem, safe_path, _alive
    by_path={i.path:i for i in files};result={}
    studio=paths.user_data_root/'SubtitleStudioPreview'
    def load(path):
        if not safe_path(path,(paths.cache_root,studio,paths.log_root)):return {}
        try:
            if path.stat().st_size>1024*1024:return {}
            data=json.loads(path.read_text('utf8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}
    starts=None
    def consumer_starts():
        nonlocal starts
        if starts is None:
            starts=[]
            try:
                import psutil
                starts=[psutil.Process(pid).create_time() for pid in legacy_consumers()]
            except Exception:pass
        return starts
    def add(path,category,producer,source='',protected='',warning=''):
        if str(path) not in by_path:return
        item=by_path[str(path)]
        if item.producer or '链接' in item.reason or '共享硬链接' in item.reason or '索引读取失败' in item.reason or item.reason.startswith(('正在生成','扫描期间')):return
        if source and not Path(source).is_file() and category in {'waveform','thumbnail'}:
            warning='原素材未恢复前无法重新生成这些预览'
            protected='原素材不可访问；辅助预览仅可手动确认清理'
        result[str(path)]=CacheItem(item.path,category,item.size,None,producer,source,
            protected or '已识别生成契约；请确认登记后纳入清理', 'local',item.identity,warning)
    for item in files:
        path=Path(item.path)
        if item.producer:continue
        if path.parent==paths.cache_root/'advanced-preview' and re.fullmatch(r'[0-9a-f]{64}\.png',path.name):
            try:
                with path.open('rb') as stream:header=stream.read(24)
                if header[:8]==b'\x89PNG\r\n\x1a\n' and header[12:16]==b'IHDR':add(path,'preview','advanced_preview_pixels_legacy')
            except OSError:pass
        # Historical local audio is identified by its producer receipt and NPY
        # header. Recognition text/remote answers next to it are never adopted.
        if path.name=='audio_meta.json' and path.parent.parent==paths.cache_root and re.fullmatch(r'[0-9a-f]{24}',path.parent.name):
            data=load(path);identity=data.get('identity') or {};source=identity.get('path','')
            audio=path.with_name('audio_16k.npy')
            if (data.get('schema')==3 and isinstance(source,str) and source and isinstance(identity.get('size'),int)
                    and isinstance(identity.get('mtime_ns'),int) and data.get('sample_rate')==16000
                    and isinstance(data.get('samples'),int) and data['samples']>=0
                    and re.fullmatch(r'[0-9a-f]{64}',str(data.get('signature','')))):
                try:
                    import numpy.lib.format as fmt
                    with audio.open('rb') as stream:
                        version=fmt.read_magic(stream);shape,fortran,dtype=fmt._read_array_header(stream,version,max_header_size=8192)
                        valid=not fortran and shape==(data['samples'],) and dtype.str in {'<f4','<f8'} and stream.tell()+data['samples']*dtype.itemsize==by_path[str(audio)].size
                    if valid:
                        protected='' if Path(source).is_file() else '原素材不可访问；可能是唯一音频副本'
                        add(path,'audio','cache_shared_audio_legacy',source,protected);add(audio,'audio','cache_shared_audio_legacy',source,protected)
                except (OSError,ValueError,KeyError):pass
        # The exact event producer contract, rather than a .jsonl extension.
        match=re.fullmatch(r'auto_asr_\d{8}_\d{6}_(\d+)_[0-9a-f]{6}\.jsonl',path.name)
        if path.parent==paths.log_root and match and safe_path(path,(paths.log_root,)):
            try:
                with path.open('r',encoding='utf8') as stream:first=stream.readline(8193)
                data=json.loads(first) if len(first)<=8192 else {}
                if (isinstance(data,dict) and data.get('event')=='run_started'
                        and data.get('pid')==int(match[1])
                        and all(isinstance(data.get(k),str) and bool(data[k]) for k in
                                ('time','pipeline_build','core_path','startup_self_test'))):
                    add(path,'log','cache_run_event_log_legacy',protected='本次识别诊断日志仍有活动进程写入' if _alive(f'{int(match[1])}:unknown') else '')
            except (OSError,ValueError):pass
        # Known diagnostics must carry their producer payload, not just .json.
        if path.parent in {paths.log_root/'ai_design',studio/'logs'/'ai_design'} and re.fullmatch(r'design-\d{8}-\d{6}-\d{6}\.json',path.name):
            data=load(path)
            if data.get('schema_version')==1 and data.get('stage')=='studio_visual_design' and isinstance(data.get('final'),dict):
                add(path,'log','studio_design_diagnostic_legacy')
        if path==paths.log_root/'2byteasr-startup.log':
            try:
                with path.open(encoding='utf8',errors='replace') as stream:first=stream.readline(1024)
                if first.startswith('=== 2ByteASR packaged cold start pid='):add(path,'log','packaged_startup_log_legacy')
            except OSError:pass
        if path==paths.log_root/'studio-open.log':
            try:
                with path.open(encoding='utf8',errors='replace') as stream:first=stream.readline(2048)
                if re.match(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\] event=[A-Z][A-Z_0-9]+(?: |\n)',first):
                    module=sys.modules.get('twobyteasr.runtime_trace');writer=getattr(module,'GLOBAL_STUDIO_TRACE',None)
                    thread=getattr(writer,'_thread',None)
                    writer_path=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'2ByteASR/logs/studio-open.log'
                    active=bool(consumer_starts() or thread and thread.is_alive() and path==writer_path)
                    add(path,'log','studio_runtime_trace_legacy',protected='当前应用诊断日志仍在写入；关闭对应应用后可清理' if active else '')
            except OSError:pass
        # The rotated-out trace (runtime_trace.TRACE_LOG_MAX_BYTES) is never written again.
        if path==paths.log_root/'studio-open.previous.log':
            try:
                with path.open(encoding='utf8',errors='replace') as stream:first=stream.readline(2048)
                if re.match(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\] event=[A-Z][A-Z_0-9]+(?: |\n)',first):
                    add(path,'log','studio_runtime_trace_legacy')
            except OSError:pass
        if path.parent==paths.log_root and (path.name=='startup-trace.jsonl' or re.fullmatch(r'processes-(\d+)\.jsonl',path.name)):
            try:
                with path.open(encoding='utf8') as stream:first=stream.readline(8193)
                data=json.loads(first) if len(first)<=8192 else {}
                if path.name=='startup-trace.jsonl' and isinstance(data,dict) and {'run_id','pid','stage','utc_ms','elapsed_ms'}.issubset(data):
                    add(path,'log','startup_milestone_trace_legacy')
                elif isinstance(data,dict) and data.get('phase')=='start' and isinstance(data.get('parent_pid'),int) and data.get('parent_pid')==int(re.fullmatch(r'processes-(\d+)\.jsonl',path.name)[1]) and {'timestamp','root_pid'}.issubset(data):
                    add(path,'log','child_process_diagnostic_legacy',protected='该进程仍活动，诊断记录保留' if _alive(f"{data['parent_pid']}:unknown") else '')
            except (OSError,ValueError,TypeError):pass
        if path==studio/'logs'/'mpv.log':
            try:
                with path.open(encoding='utf8',errors='replace') as stream:first=stream.readline(1024)
                if re.match(r'\[\s*[\d.]+\]\[v\]\[cplayer\] mpv v',first):add(path,'log','mpv_diagnostic_log_legacy')
            except OSError:pass
        # IndexedMediaCache v2's required source identity and codec/length receipt.
        if path.name in {'ready.json','origin.json'} and path.parent.parent.name=='v2' and path.parent.parent.parent==paths.cache_root/'media'/'seek':
            data=load(path);source=str(data.get('source') or '')
            if source and isinstance(data.get('size'),int) and isinstance(data.get('mtime_ns'),int):
                protected='' if Path(source).is_file() else '原素材不可访问；先保存为工程资产／重新定位'
                if not protected:
                    try:
                        original=Path(source).stat()
                        if (original.st_size,original.st_mtime_ns)!=(data['size'],data['mtime_ns']):protected='原素材身份已变化；中间副本保持保护'
                    except OSError:protected='原素材不可访问；先保存为工程资产／重新定位'
                for leaf in ('optimized.mp4','optimized.mkv','continuous.mkv','ready.json','origin.json','sync-map.json'):
                    add(path.parent/leaf,'media','indexed_media_legacy',source,protected)
        # WaveformMetadata schema + enumerated float arrays, never arbitrary JSONs.
        if path.name=='metadata.json' and path.is_relative_to(studio/'waveform-cache'):
            data=load(path)
            if data.get('source_path') and isinstance(data.get('levels'),list) and data.get('schema_version') and not data.get('incomplete',False):
                levels=data['levels'];valid=all(isinstance(v,dict) and re.fullmatch(r'(lod\d+|outline)\.f32',str(v.get('file',''))) and isinstance(v.get('frames'),int) and v['frames']>=0 for v in levels)
                if valid:
                    add(path,'waveform','waveform_cache_legacy',str(data['source_path']))
                    for level in levels:
                        leaf=path.parent/level['file']
                        if str(leaf) in by_path and by_path[str(leaf)].size==level['frames']*8:
                            add(leaf,'waveform','waveform_cache_legacy',str(data['source_path']))
        # Filmstrip v3 sidecar contract is a seek/time/LOD receipt.
        if path.suffix=='.json' and path.parent==studio/'filmstrip-v3':
            data=load(path)
            match=re.fullmatch(r'[0-9a-f]{24}(?:-missing)?-t(\d+)-(\d+)x72-lod(\d+)-srgb3',path.stem)
            if (match and isinstance(data.get('exact'),bool) and data.get('requested_ms')==int(match[1])
                    and data.get('lod_ms')==int(match[3]) and isinstance(data.get('pts_ms'),(float,int))):
                warning='历史缩略图未保存原素材路径；清理后原素材未恢复前无法重新生成这些预览'
                add(path,'thumbnail','video_filmstrip_legacy',warning=warning);add(path.with_suffix('.jpg'),'thumbnail','video_filmstrip_legacy',warning=warning)
        # Old mpv publishers used known immutable slots in a UUID session.
        if path.suffix=='.rgba' and path.is_relative_to(studio/'mpv-overlays'):
            relative=path.relative_to(studio/'mpv-overlays')
            if len(relative.parts)<2 or not re.fullmatch(r'[0-9a-f]{32}',relative.parts[0]):continue
            session=studio/'mpv-overlays'/relative.parts[0];owner=load(session/'owner.json')
            known=bool(re.fullmatch(r'(?:web-)?overlay-\d+-(?:sync-)?\d+\.rgba',path.name)) or (path.parent.name in {'caption-prepared','caption-scenes'} and re.fullmatch(r'(?:(?:native-)?[0-9a-f]+(?:-[01])?|native-[0-9a-f]+-\d+-[01])\.rgba',path.name))
            if owner.get('producer')=='mpv_overlay_session' and owner.get('schema')==1:
                if not isinstance(owner.get('pid'),int) or not isinstance(owner.get('create_time'),(float,int)) or owner['pid']<1 or owner['create_time']<=0:continue
                identity=f"{owner['pid']}:{owner['create_time']:.6f}"
                reason='活动覆盖层会话' if _alive(identity) else ''
                if known:add(path,'overlay','mpv_overlay_session_legacy',protected=reason)
            elif known:
                # UUID slots were created per process, never reused. Only a
                # session modified during a still-live legacy app is ambiguous.
                active_starts=consumer_starts()
                recent=bool(active_starts and path.stat().st_mtime>=min(active_starts))
                add(path,'overlay','mpv_overlay_slot_legacy',protected='旧覆盖层会话可能仍由活动播放器使用；会话归属待核对' if recent else '')
    return result


def adopt(service,items,*,cancel=None):
    fresh=service.scan(cancel,include_models=False)
    recognized={i.path:i for i in fresh.items if i.producer.endswith('_legacy')};count=0;skipped=[]
    from .storage_service import safe_path, _alive
    with service._db() as db:
        db.execute('BEGIN IMMEDIATE')
        for item in items:
            if cancel is not None and cancel.is_set():break
            current=recognized.get(item.path)
            if not current or current.identity!=item.identity or not current.manual_cleanable or service.manual_busy():
                skipped.append(dict(path=item.path,reason='来源、身份或实际占用状态变化'));continue
            try:
                st=Path(current.path).lstat()
                owners=db.execute('SELECT owner FROM leases WHERE path=?',(current.path,)).fetchall()
                if not safe_path(current.path,service.roots) or st.st_nlink>1 or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)!=current.identity or any(_alive(o[0]) for o in owners):
                    skipped.append(dict(path=item.path,reason='删除前身份／路径／活动租约变化'));continue
                inserted=db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO NOTHING',
                    (current.path,current.category,current.producer,current.source,'local','仅手动确认：'+current.warning if current.warning else '',None))
                if inserted.rowcount:count+=1
                else:skipped.append(dict(path=item.path,reason='归属已登记或并发变化；需刷新确认'))
            except OSError as exc:skipped.append(dict(path=item.path,reason=str(exc)))
    return dict(registered=count,skipped=skipped)
