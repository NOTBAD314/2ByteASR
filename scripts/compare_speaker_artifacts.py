"""Global label correspondence and review intervals, never fake accuracy."""
import csv
import json
import sys
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from twobyteasr.nemotron_diarization import merge


def compare(root):
    root=Path(root)
    load=lambda p:json.loads((root/p).read_text('utf8'))
    rows=load('frozen-cues.json')
    a=np.load(root/'nemotron/official-offline-activity.npy')[:4800]
    b=np.load(root/'nemotron/project-activity.npy')
    moss=load('moss.json')['chunks'][0]['segments']
    labels=list(dict.fromkeys(r['speaker'] for r in moss))
    n=min(len(a),len(b)); a=a[:n];b=b[:n]
    c=np.zeros((n,len(labels)))
    for row in moss:
        c[max(0,round(row['start']*100)):min(n,round(row['end']*100)),labels.index(row['speaker'])]=1
    score=(b>=.5).astype(float).T@c
    ix,iy=linear_sum_assignment(-score)
    mapping={int(i):labels[j] for i,j in zip(ix,iy) if score[i,j]>0}
    ax,ay=linear_sum_assignment(-((a>=.5).astype(float).T@(b>=.5).astype(float)))
    ab_mapping=dict(zip(map(int,ax),map(int,ay)))
    assignments={name:merge(rows,values,.01) for name,values in [('official_offline',a),('project',b)]}
    review=[]
    for i,row in enumerate(rows):
        lo=max(0,int(row['start']*100));hi=min(n,int(np.ceil(row['end']*100)))
        support=c[lo:hi].mean(0)
        selected=labels[int(np.argmax(support))] if max(support)>.55 else 'UNASSIGNED'
        project=assignments['project'][i]
        raw=project['speaker']
        mapped=mapping.get(int(raw.split('_')[1])-1,'unmatched') if raw.startswith('NEMO_') else raw
        review.append(dict(id=row['id'],source_start=row['start']+12,source_end=row['end']+12,
            frozen_text=row['text'],old_project=row['original_speaker'],
            official_offline=assignments['official_offline'][i]['speaker'],project=raw,
            project_global_mapping=mapped,moss_activity=selected,moss_support=float(max(support)),
            difference=mapped!=selected,review_required=True))
    result=dict(human_reference=False,metrics_are_agreement_not_accuracy=True,
        sample_source_range=[12,60],collar_seconds=0,frame_step_seconds=.01,
        official_offline_to_project_global_mapping=ab_mapping,
        offline_stream_any_activity_frame_disagreement=float(np.mean(np.any((a>=.5)!=(b[:,ay]>=.5),axis=1))),
        project_to_moss_global_mapping=mapping,project_channel_seconds=((b>=.5).sum(0)*.01).tolist(),
        moss_labels=labels,overlap_matrix_seconds=(score*.01).tolist(),
        frozen_cue_assignment_agreement=sum(x['speaker']==y['speaker'] for x,y in zip(assignments['official_offline'],assignments['project'])),
        frozen_cue_count=len(rows),unassigned_cues=sum(r['project']=='UNASSIGNED' for r in review),
        difference_rows=sum(r['difference'] for r in review),review=review,
        note='One correspondence over the complete sample, never rematched by chunk. MOSS text is not substituted. No human DER or accuracy.')
    (root/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    with (root/'review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(review[0]));writer.writeheader();writer.writerows(review)
    for name,value in assignments.items():
        (root/(name+'-final-assignment.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'review','overlap_matrix_seconds'}},ensure_ascii=False))


if __name__=='__main__':compare(sys.argv[1])
