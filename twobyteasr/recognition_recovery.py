"""Idempotent recovery from committed outputs; never re-run ASR or overwrite edits."""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace


def recover_report(report_path, *, recovery_root=None):
    from .studio_project import (load_project, save_project, project_library_root,
        project_from_runtime_cues, parse_subtitle_timecode_ms)
    report_path=Path(report_path).resolve()
    raw=report_path.read_bytes();report=json.loads(raw.decode('utf-8-sig'))
    outputs=report.get('result',{}).get('outputs') or report.get('outputs') or {}
    identity=hashlib.sha256(raw).hexdigest()[:20]
    def resolve(value):
        path=Path(str(value))
        return path if path.is_absolute() else report_path.parent/path
    committed=resolve(outputs['project']) if outputs.get('project') else None
    source=None
    if committed and committed.is_file():
        try:source=load_project(committed)
        except (ValueError,OSError):pass
        if source is not None and source.cues and recovery_root is None:return committed
    target=Path(recovery_root or project_library_root()/'Recovered')/identity/'恢复的字幕工程.2byteproj'
    # Once offered to the user this is an editable project, not a disposable cache.
    if target.is_file():
        load_project(target)
        return target
    if source is None or not source.cues:
        srt=resolve(outputs.get('srt',''))
        if not outputs.get('srt') or not srt.is_file():raise ValueError('报告没有可恢复的工程或 SRT；原始输出保持不变')
        cues=[]
        for block in re.split(r'\r?\n\s*\r?\n',srt.read_text('utf-8-sig').strip()):
            lines=block.splitlines()
            position=next((i for i,line in enumerate(lines) if '-->' in line),None)
            if position is None:continue
            a,b=lines[position].split('-->',1)
            start,end=parse_subtitle_timecode_ms(a.strip()),parse_subtitle_timecode_ms(b.strip().split()[0])
            text='\n'.join(lines[position+1:]).strip()
            if start is None or end is None or end<=start or not text:raise ValueError('SRT含无效时间或正文，停止恢复')
            cues.append(SimpleNamespace(cue_id=len(cues)+1,start=start/1000,end=end/1000,text=text,speaker='S00'))
        if not cues:raise ValueError('SRT没有有效字幕，停止恢复')
        media=str(report.get('media',{}).get('path') or '')
        if not media:raise ValueError('报告缺少原素材身份')
        source=project_from_runtime_cues(media,cues,report_path=str(report_path),original_outputs=outputs)
    source.generation_metadata=dict(source.generation_metadata or {})
    source.generation_metadata['recognition_recovery']={'report_sha256':hashlib.sha256(raw).hexdigest(),
        'source_project':str(committed or ''),'source_report':str(report_path),'policy':'reuse-existing-never-overwrite'}
    save_project(source,target)
    reopened=load_project(target)
    if len(reopened.cues)!=len(source.cues):raise ValueError('恢复工程保存校验失败')
    return target
