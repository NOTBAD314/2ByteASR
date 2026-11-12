"""Read-only delivery audit: stable IDs and reasons, never count-only inference."""
import argparse,collections,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--final-cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--module-root',type=Path)
    parser.add_argument('--source-cache',type=Path,help='Recorded unified primary cache for full source-text replay')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if args.module_root:sys.path.insert(0,str(args.module_root.resolve()))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile');os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.projects.studio_project import load_project,save_project
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.subtitle_rules.current_issues import current_issue_view
    from twobyteasr.recognition.speech_coverage import _text_snapshot,text_retained
    journal=json.loads(args.journal.read_text(encoding='utf-8-sig'))
    timed=json.loads(args.final_cache.read_text(encoding='utf-8-sig'))['data']
    project=load_project(args.project)
    project._qc_result=SubtitleQCEngine().analyze(project)
    view=current_issue_view(project)
    raw=json.loads(args.project.read_text(encoding='utf-8-sig'))
    generated={str(c['cue_id']):c for c in timed};persisted={str(c['id']):c for c in raw['cues']};current={c.id:c for c in project.cues}
    snapshot=_text_snapshot(project.cues)
    source=(project.generation_metadata.get('speaker_recovery') or {}).get('raw_segments',[])
    parents=_text_snapshot(source)
    scope=next(e for e in journal['events'] if e['event']=='asr_review_scope')['ranges']
    gap_checks=[]
    for gap in journal['result']['speech_coverage']['gaps']:
        if gap.get('first_missing_stage')!='segmentation':continue
        linked=[r for r in parents if min(r['end'],gap['end'])>max(r['start'],gap['start'])]
        gap_checks.append(dict(id=gap['id'],window=[gap['start'],gap['end']],source_ids=[r['id'] for r in linked],
            all_source_text_retained=bool(linked) and all(text_retained(r,snapshot) for r in linked),
            review_windows=[r for r in scope if r['start']<=gap['start'] and r['end']>=gap['end']],
            acoustic_listening='not_performed',recovery_requests=0))
    trace=[]
    records=project.generation_metadata.get('translation_records',{}).get('records',{})
    spans=project.generation_metadata.get('segmentation_source_spans',{}).get('cues',{})
    for cue_id,cue in generated.items():
        trace.append(dict(cue_id=cue_id,speaker_id=cue['speaker'],start=cue['start'],end=cue['end'],
            text_sha256=hashlib.sha256(cue['text'].encode()).hexdigest(),parents=cue.get('source_spans',[]),
            saved=cue_id in persisted,loaded=cue_id in current,translated=bool(records.get(cue_id,{}).get('text')),
            saved_parent_mapping=spans.get(cue_id,{})))
    result=dict(job_id=journal['job_id'],journal_status=journal['status'],delivery=journal['task']['results'][0]['status'],
        stage_counts=journal['result']['transcript_counts'],final_cache_count=len(timed),raw_project_count=len(persisted),loaded_project_count=len(current),
        dropped_at_project_build=[dict(cue_id=k,text=generated[k]['text'],speaker_id=generated[k]['speaker'],
            reason='low-share-speakers-v1 automatic ignore',restored=k in current) for k in generated.keys()-persisted.keys()],
        polishing=journal['polishing_summary'],legacy_review_items=len(journal['review_items']),
        legacy_review_categories=dict(collections.Counter(r['category'] for r in journal['review_items'])),
        current_review=dict(counts=view.counts(),totals=view.totals(),statistics=view.statistics()),
        gaps=gap_checks,trace=trace,original_project_sha256=hashlib.sha256(args.project.read_bytes()).hexdigest(),
        limits=['No paid API request','No claim of semantic translation acceptance','No original audio listening verdict'])
    if args.source_cache:
        import copy
        import subtitle_core as core
        from types import SimpleNamespace
        from twobyteasr.subtitle_rules.language_rules import language_scope
        from twobyteasr.recognition.speech_coverage import checkpoint
        before=core.deserialize_segments(json.loads(args.source_cache.read_text(encoding='utf-8-sig'))['data'])
        prepared=copy.deepcopy(before)
        final={str(e['cue_id']):e['details']['final_text'] for e in journal['events'] if e['event']=='terminology_polish_final'}
        for row in prepared:
            if str(row.segment_id) in final:row.text=final[str(row.segment_id)];row.final_text=row.text
        with language_scope(stored_language(project)):
            prepared=core.apply_editorial_segment_rules(prepared)
        runtime=[SimpleNamespace(cue_id=c.id,start=c.start_ms/1000,end=c.end_ms/1000,text=c.text,speaker=c.speaker_id,
            source_spans=spans.get(c.id,{}).get('parts',[])) for c in project.cues]
        state=dict(identity=journal['result']['speech_coverage']['identity'],gaps=[],stages=[],speech_ranges=journal['result']['speech_coverage']['speech_ranges'])
        checkpoint(state,'speaker_filter',before);checkpoint(state,'prepared_source',prepared)
        checkpoint(state,'segmentation',runtime);checkpoint(state,'final_cues',runtime)
        result['source_replay']=dict(input_segments=len(before),adopted_segments=len(prepared),final_cues=len(runtime),
            source_ids_preserved=[c.segment_id for c in before]==[c.segment_id for c in prepared],
            upstream_changes=state['stages'][1]['source_changes'],new_text_gaps=state['gaps'],
            semantic_and_acoustic_verification='not_established_by_this_replay')
    (out/'trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    save_project(project,out/'recovered.2byteproj')
    reopened=load_project(out/'recovered.2byteproj')
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    artifacts=export_language_layers(project,out/'subtitles','recovered',layers=('original','translation','bilingual'))
    result['subtitle_exports']=[str(a.path) for a in artifacts.artifacts]
    for file in (out/'subtitles').glob('*.srt'):
        text=file.read_text(encoding='utf-8-sig')
        if '.ja.' in file.name:assert '泣くなお前には来年がある' in text
    (out/'trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    assert {c.id:c.text for c in reopened.cues}=={c.id:c.text for c in project.cues}
    print(json.dumps(dict(count=len(project.cues),dropped=result['dropped_at_project_build'],reviews=result['current_review'],gaps=gap_checks),ensure_ascii=False))
def stored_language(project):
    from twobyteasr.subtitle_rules.language_rules import project_language
    return project_language(project)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
