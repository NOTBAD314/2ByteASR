"""Bounded independent candidates. Only this coordinator writes the parent ledger."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED


def run_candidates(ledger,rows,worker,*,concurrency,cancel_check,event_callback,request_id):
    from .caption_creative_pipeline import ThemeLedger,canonical,digest
    from .studio_ai import AIWebThemeSuggestion
    started=time.monotonic();lock=threading.RLock();concepts={};states={}
    concurrency=max(1,min(3,int(concurrency)))
    ledger.value['scheduling']=dict(requested_candidates=len(rows),configured_concurrency=concurrency,
        actual_peak_candidates=0,provider_limit='provider broker also applies its configured limits')
    for row in rows:states[row['id']]=dict(status='queued',stage='application_queue',queued_at=time.time())
    def publish(event=None):
        ordered=[concepts[r['id']] for r in rows if r['id'] in concepts]
        ledger.value.update(candidate_states=copy.deepcopy(states),partial_concepts=copy.deepcopy(ordered))
        ledger.save()
        if event_callback:
            data=dict(event or {},name='candidate_progress',request_id=request_id+'/candidates',
                label='候选独立进行',status='running',started_monotonic=started,
                **__import__('twobyteasr.design_progress',fromlist=['aggregate_activity']).aggregate_activity(states),partial_concepts=copy.deepcopy(ordered),
                candidate_states=copy.deepcopy(states),
                brief={k:ledger.value[k] for k in ('raw_user_prompt','raw_prompt_hash','theme')},
                pending_directions=[r for r in rows if r['id'] not in concepts])
            event_callback(data)
    def run(row):
        ident=row['id']
        with lock:
            states[ident].update(status='running',stage='implementation',started_at=time.time())
            peak=sum(s['status']=='running' for s in states.values())
            ledger.value['scheduling']['actual_peak_candidates']=max(peak,ledger.value['scheduling']['actual_peak_candidates'])
            publish()
        def progress(event):
            with lock:
                states[ident].update(stage=event.get('label','implementation'),activity=event)
                publish(event)
        try:return worker(row,progress)
        finally:
            with lock:states[ident]['status']='finishing'
    with ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix='caption-candidate') as pool:
        futures={pool.submit(run,row):row for row in rows}
        while futures:
            done,_=wait(futures,timeout=.1,return_when=FIRST_COMPLETED)
            for future in done:
                row=futures.pop(future);ident=row['id']
                try:
                    result,child=future.result()
                    concept=result.concepts[0]
                    state=copy.deepcopy(child.value['candidate_states'][ident])
                    invocations=copy.deepcopy(child.value.get('invocations',[]))
                    sources=copy.deepcopy(child.value.get('candidates',[]))
                except Exception as exc:
                    concept=dict(id=ident,name=row['name'],composition='此方向未完成',technical_status='failed',
                        technical_errors=[dict(category=getattr(exc,'category','cancelled' if cancel_check and cancel_check() else 'implementation_error'),constraint=str(exc))])
                    state=dict(status='cancelled' if '取消' in str(exc) else 'failed',stage='terminal');invocations=[];sources=[]
                with lock:
                    concepts[ident]=concept;states[ident].update(state,finished_at=time.time())
                    ledger.value.setdefault('invocations',[]).extend(invocations)
                    ledger.value.setdefault('candidates',[]).extend(sources)
                    publish()
    ordered=[concepts[r['id']] for r in rows]
    usable=sum(c.get('technical_status')!='failed' for c in ordered)
    ledger.value.update(status='ready' if usable else 'failed',elapsed_seconds=time.monotonic()-started)
    # Recovery owns the same complete source definitions, never a new generation.
    payload={'candidates':[dict(r,generated_source=next((c['generated_source'] for c in ledger.value['candidates'] if c['id']==r['id']),{})) for r in rows]}
    path=ledger.root/'provider-assembled.json';path.write_text(canonical(payload),'utf8')
    ledger.value['raw_response']=dict(path=str(path),sha256=digest(path.read_bytes()),completed=True,kind='assembled_stages')
    ledger.save()
    return AIWebThemeSuggestion(theme={},source='concepts',message=f'{usable}/{len(rows)}稿可用',request_id=request_id,
        provider=ledger.value['provider']['provider'],model=ledger.value['provider']['model'],
        brief={k:ledger.value[k] for k in ('raw_user_prompt','raw_prompt_hash','theme')},concepts=ordered,
        selected_concept_id='',quality={'design_version':4,'creative_version':'caption-creative-source-9','ledger_path':str(ledger.root/'ledger.json')})
