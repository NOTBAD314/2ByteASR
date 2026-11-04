"""Materialize only checksum-verified saved ranges; never call a provider."""
from __future__ import annotations
import json
from pathlib import Path
import time

from .task_journal import TaskJournal,FileLease,read_record,digest


def build(job_id):
    from .service import MediaResult,QueueResult
    import subtitle_core as legacy
    from ..projects.studio_project import create_studio_outputs
    from .recognition_result import media_identity_for_task
    journal=TaskJournal(job_id)
    with FileLease(journal.directory/'executor.lock'):
        journal.record=read_record(journal.path)
        task=journal.record['task']
        inputs=task['inputs']
        if len(inputs)!=1:
            raise ValueError('请从各素材已完成的工程查看结果。')
        cues=[];segments=[];seen=set();ranges=[]
        metadata={}
        def merge(target,value):
            for key,item in value.items():
                if isinstance(item,dict):merge(target.setdefault(key,{}),item)
                elif key in target and target[key]!=item:raise ValueError('分片译文设置冲突。')
                else:target[key]=item
        for receipt in task.get('artifacts',{}).values():
            row=json.loads(Path(receipt['path']).read_text(encoding='utf-8'))
            if not str(row.get('key','')).startswith('delivery:') or digest(row['payload'])!=row['sha256']:continue
            data=row['payload'];args=data['arguments']
            cues=args['cues'];segments=args['segments']
            metadata.update(data.get('translation') or {})
            break
        if not cues:
            from .streaming_recognition import _digest
            for root in task.get('cache_directories',{}):
                for path in sorted((Path(root)/'ready-shards').glob('r*.json')):
                    try:
                        row=json.loads(path.read_text(encoding='utf-8'));data=row['data']
                        if row.get('checksum')!=_digest(data):continue
                        # Only one current version of a shard, as recorded by its input file.
                        input_path=path.with_name(path.stem+'-input.json')
                        if not input_path.is_file():continue
                        index=int(data['index'])
                        current=task.get('shards',{}).get(f'r{index+1:03}',{})
                        if current.get('status')!='completed' or current.get('version')!=row.get('version'):continue
                        if index in seen:continue
                        seen.add(index)
                        from types import SimpleNamespace
                        from .shard_identity import namespace_result
                        part=SimpleNamespace(index=index,segments=legacy.deserialize_segments(data['segments']),
                            cues=legacy.deserialize_cues(data['cues']),reviews=[])
                        namespace_result(part)
                        cues.extend(legacy.serialize_cues(part.cues));segments.extend(legacy.serialize_segments(part.segments))
                        merge(metadata,data.get('translation') or {})
                    except (OSError,ValueError,KeyError,TypeError):continue
        if not cues:raise ValueError('目前只有原始识别证据，尚无完整可用字幕分片；可继续处理。')
        cues.sort(key=lambda r:(r['start'],r['end'],r['cue_id']))
        if len({row['cue_id'] for row in cues})!=len(cues):raise ValueError('已有结果含重复身份，拒绝混合不同分片版本。')
        media=inputs[0]['path'];identity=media_identity_for_task(media)
        known=list(task.get('cache_directories',{}).values())
        if known and any(row.get('sha256') and row['sha256']!=identity['sha256'] for row in known):
            raise ValueError('素材已经改变，保留原检查点；请重新定位原素材。')
        metadata.update(job_id=job_id,media_identity=identity,recognition_partial={
            'source_task':job_id,'state':journal.record['status'],'complete':False,
            'ranges':[[r['start'],r['end']] for r in cues],
            'notice':'仅包含已保存的字幕，缺失区间需继续处理。'})
        saved=journal.directory/'partial-result'/digest(cues)[:20]/'project.2byteproj'
        decoded_cues=legacy.deserialize_cues(cues)
        decoded_segments=legacy.deserialize_segments(segments)
        for cue,row in zip(decoded_cues,cues):
            if 'forced_alignment' in row:cue.forced_alignment=row['forced_alignment']
        for segment,row in zip(decoded_segments,segments):
            if 'caption_arbitration' in row:segment.caption_arbitration=row['caption_arbitration']
        output=create_studio_outputs(media,decoded_cues,txt_path='',
            segments=decoded_segments,generation_metadata=metadata,target_project_path=saved)
        reference=json.loads(output.get('result_ref_json') or '{}')
        journal.record['result'].update(cue_count=len(cues),outputs={'project':output['project'],'result_ref_json':output['result_ref_json']})
        task['partial_preview']=output['project'];journal._save()
        result=MediaResult(media,'degraded_success',job_id=job_id,project_path=output['project'],
            project_id=reference.get('project_id',''),result_revision=reference.get('result_revision',''),
            media_fingerprint=reference.get('media_fingerprint',''),result_ref_json=json.dumps(reference),
            report_json_path=str(journal.path),error='仅显示已保存范围；任务尚未全部完成。')
        return QueueResult((result,),0.,job_id=job_id)
