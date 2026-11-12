"""Export local listening samples and source lineage without touching an original project."""
import argparse,json,os,random,subprocess,sys,html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--count',type=int,default=45)
    parser.add_argument('--audio',action='store_true');parser.add_argument('--qwen-generation',type=Path)
    a=parser.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('use fresh source/tmp output')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.diagnostics.subtitle_lineage import subtitle_lineage
    from twobyteasr.glossary.recognition_review_import import existing_review
    from twobyteasr.studio.subtitle_text_targets import text_entries
    project=load_project(a.project);rows=[subtitle_lineage(project,c.id) for c in project.cues]
    difficult=[r for r in rows if any(s['polish'].get('rejected_edits') or s['polish'].get('accepted_edits')
        or 433==s['source_segment_id'] or any(needle in (s['original_asr'] or '')
            for needle in ('じゃあ上星','ギブギブ','言わないで','カイロショート')) for s in r['source_chain'])]
    critical=[r for r in difficult if any(s['source_segment_id'] in {240,326,433} or s['polish'].get('accepted_edits')
        or any(needle in (s['original_asr'] or '') for needle in ('じゃあ上星','ギブギブ','言わないで')) for s in r['source_chain'])]
    rest=[r for r in difficult if r not in critical];random.Random(20261112).shuffle(rest)
    chosen=(critical+rest)[:min(30,a.count-10)];ids={r['cue_id'] for r in chosen}
    normal=[r for r in rows if r['cue_id'] not in ids and r not in difficult]
    random.Random(23).shuffle(normal);chosen+=normal[:max(0,a.count-len(chosen))]
    chosen.sort(key=lambda r:r['start_ms'])
    generations=json.loads(a.qwen_generation.read_text('utf8'))['results'] if a.qwen_generation else []
    for number,row in enumerate(chosen,1):
        row['sample_id']=f'sample-{number:02d}';row['selection']='difficult' if row in difficult else 'random_control'
        for source in row['source_chain']:
            start,end=source['time']
            source['reference_generation_windows']=[{'source_window_id':w['segment_id'],'start':w['start'],'end':w['end'],
                'request_language':w.get('request_language'),'generation':w.get('generation'),
                'basis':'local exact-PCM replay; original HTTP/run stop information was not recorded'}
                for w in generations if w['start']*1000<end and w['end']*1000>start]
        if a.audio:
            start=max(0,row['start_ms']/1000-1.5);end=row['end_ms']/1000+1.5
            path=out/(row['sample_id']+'.wav')
            subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-ss',str(start),
                '-i',project.media.path,'-t',str(end-start),'-vn','-ac','1','-ar','16000',str(path)],
                check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            row['listening_audio']=path.name
    imported=existing_review(project,text_entries(project,mode='original'))
    result={'sample_count':len(chosen),'project_cues':len(project.cues),'manual_listening_performed':False,
        'source_mapping':'stored segment IDs and exact character spans; never cue array position',
        'review_import':imported.receipt,'samples':chosen}
    (out/'samples.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    cards=[]
    for row in chosen:
        escaped=html.escape(json.dumps(row,ensure_ascii=False,indent=2))
        cards.append(f"<article><h2>{row['sample_id']} · {row['start_ms']/1000:.3f}s · {row['selection']}</h2>"
            f"<p>{html.escape(row['editable_primary_text'])}</p><p>{html.escape(row['translation'])}</p>"
            f"<audio controls src='{row.get('listening_audio','')}'></audio>"
            "<p>标注尚待人工试听；模型与代码验证不等于正确台词。</p>"
            f"<textarea data-key='{row['sample_id']}' placeholder='试听后记录原文、译文判断与依据'></textarea>"
            f"<details><summary>完整来源链</summary><pre>{escaped}</pre></details></article>")
    (out/'index.html').write_text('<!doctype html><meta charset=utf-8><title>日语字幕试听样本</title>'
        '<style>body{max-width:1000px;margin:40px auto;background:#f4efe6;color:#302b24;font:17px/1.7 sans-serif}'
        'article{padding:24px;border-top:1px solid #c6bcae}textarea{width:95%;height:90px}pre{white-space:pre-wrap;font-size:13px}</style>'
        f'<h1>本集{len(chosen)}个待试听样本</h1><p>真实工程/真实原音切片。困难样本与随机对照混合；尚无人工真值，不计算准确率。</p>'
        +''.join(cards)+"<script>document.querySelectorAll('textarea').forEach(e=>{e.value=localStorage.getItem('ja-20261112-'+e.dataset.key)||'';"
        "e.oninput=()=>localStorage.setItem('ja-20261112-'+e.dataset.key,e.value)})</script>",'utf8')
    print(json.dumps({'samples':len(chosen),'suggestions':len(imported.hits),'pending':len(imported.receipt['pending_rows']),
        'unassigned':len(imported.receipt['unassigned']),'path':str(out)},ensure_ascii=False))
if __name__=='__main__':main()
