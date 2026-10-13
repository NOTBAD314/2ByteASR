"""Opt-in bounded audit of explicitly authorized real glossary/project writes."""
from __future__ import annotations
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def wait_state(window, page, phase):
    """Inspect both the unopened Home page and its lazily created readiness gate."""
    from PySide6.QtWidgets import QApplication
    gate=getattr(page,'_readiness',None)
    project=getattr(page,'project',None)
    controller=getattr(getattr(page,'video',None),'controller',None)
    source_profile=getattr(gate,'profile',{}) or {}
    profile={key:copy.deepcopy(value) for key,value in source_profile.items() if key!='gui_gaps_ms'}
    gaps=source_profile.get('gui_gaps_ms',())
    profile.update(gui_gap_count=len(gaps),recent_gui_gaps_ms=list(gaps[-16:]))
    pages=getattr(window,'pages',None)
    current=pages.currentWidget() if pages is not None else None
    modal=QApplication.activeModalWidget()
    label=getattr(gate,'label',None)
    return {'phase':phase,'project_path':str(getattr(page,'project_path',None) or ''),
        'project_id':getattr(project,'project_id',None),'cue_count':len(project.cues) if project else 0,
        'current_page':current.objectName() if current is not None else None,'studio_visible':page.isVisible(),
        'project_view_state':getattr(page,'_project_view_state',None),
        'readiness':{'initialized':gate is not None,'ready':bool(getattr(gate,'ready',False)),
            'active':bool(getattr(gate,'active',False)),'path':str(getattr(gate,'path','')),
            'completed':sorted(getattr(gate,'completed',())),'next_stage':getattr(gate,'next_stage',None),
            'label':label.text() if label is not None else '', 'profile':profile},
        'player_running':bool(controller and getattr(controller,'running',False)),
        'modal':modal.objectName() if modal is not None else None}


def project_ready(page, path):
    gate=getattr(page,'_readiness',None)
    loaded_path=getattr(page,'project_path',None)
    return bool(getattr(page,'project',None) and loaded_path and gate
        and Path(loaded_path).resolve()==Path(path).resolve() and gate.ready and not gate.active)


def install(output):
    import subtitle_core as legacy
    from .studio_acceptance_audit import audit_tmp_root
    output=Path(output).resolve()
    if not output.is_relative_to(audit_tmp_root()) or Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve()!=output:
        raise ValueError('Repair audit requires its declared isolated profile')
    plan=json.loads((output/'real-glossary-repair-plan.json').read_text('utf8'))
    if sha_file(plan['approved_aliases_path'])!=plan['approved_aliases_sha256']:
        raise ValueError('Approved alias manifest changed')
    if sha_file(plan['glossary_path'])!=plan['glossary_sha256_before'] or sha_file(plan['project_path'])!=plan['project_sha256_before']:
        raise ValueError('Actual objects changed after this explicitly scoped driver was prepared')
    if plan.get('resources_manifest'):
        from .glossary_live_resources import BorrowedResources,validate_manifest
        global _borrowed
        _borrowed=BorrowedResources(validate_manifest(plan['resources_manifest'],output),output)
    # The only writable personal object is this explicitly declared library.
    # Settings, recent-project indexes and all incidental caches stay isolated.
    legacy.LEARNED_TERMS_PATH=plan['glossary_path']
    if plan['live']:
        from . import llm_config
        reader=llm_config._read_secrets
        credentials=Path(os.environ['TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE']).resolve()
        llm_config._read_secrets=lambda **_kw:reader(read_only_path=credentials)
        from .asr_provider_snapshot import resolve_provider_snapshot
        provider=resolve_provider_snapshot(legacy.RUNTIME_SETTINGS,stage='polish').public_identity()
        if (provider['provider']!='deepseek' or provider['model']!='deepseek-v4-pro'
                or provider['endpoint_identity'].rstrip('/')!='https://api.deepseek.com/v1'):
            raise ValueError('Only the current approved DeepSeek/deepseek-v4-pro endpoint may be called')
        (output/'studio-replay-plan.json').write_text(json.dumps({'provider':provider},ensure_ascii=False),'utf8')
        from .glossary_review_live_guard import install as install_live_guard
        install_live_guard(output)
    else:
        from .blank_project_audit import install_offline_guards
        install_offline_guards()


def start(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_find_replace import FindReplaceDialog
    from .studio_project import load_project
    from .studio_subtitle_export import SubtitleExportOptions,export_subtitle_artifacts,verify_subtitle_artifact
    from .studio_edit_sequence import projected_cues
    from .studio_text_tools import values_from_occurrences
    from .terminology import snapshot_glossaries
    output=Path(output)
    plan=json.loads((output/'real-glossary-repair-plan.json').read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page
            self.result={'passed':False,'checks':[],'screenshots':[],'exports':[],'identity':load_build_identity().to_dict(),
                'pid':os.getpid(),'real_project':plan['project_path'],'real_glossary':plan['glossary_path'],
                'scope':'two human-authorized aliases; normal preview/apply/save; no recognition/audio/video processing',
                'live':plan['live'],'approved_manifest_sha256':plan['approved_aliases_sha256']}
            self.steps=self.run();self.waiting=0;self.busy=False;self.deadline=time.monotonic()+90
            self.phase='normal Home entry';self.last_wait_record=0;self.finished=False
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
            self.best_effort_write()

        def write(self):
            (output/'real-glossary-repair-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def reporting_error(self,stage):
            error=traceback.format_exc()
            self.result.setdefault('reporting_errors',[]).append({'stage':stage,'error':error})
            try:sys.stderr.write('Repair audit reporting failure ('+stage+'):\n'+error)
            except Exception:pass

        def best_effort_write(self):
            try:self.write()
            except Exception:self.reporting_error('result write')

        def check(self,name,value,detail=None):
            self.result['checks'].append({'name':name,'passed':bool(value),'detail':detail});self.result['progress']=name;self.write()
            if not value:raise AssertionError(f'{name}: {detail}')

        def shot(self,name,surface=None):
            _capture(surface or window,output/(name+'.png'));self.result['screenshots'].append(name+'.png');self.write()

        def wait_state(self):
            return wait_state(window,self.page,self.phase)

        def invariant(self,project):
            # Names may change. Persisted cue clocks, speakers, transforms,
            # original words/evidence and manual timeline edit positions may not.
            cues=[]
            for cue in project.cues:
                row=asdict(cue);row.pop('text',None);cues.append(row)
            from .studio_edit_sequence import sequence_of
            payload=asdict(project)
            return {'cues':cues,'speakers':payload['speakers'],'asr_evidence':copy.deepcopy(project.asr_evidence),
                'edit_sequence':sequence_of(project).to_dict(),
                'media_graph':{key:payload[key] for key in ('media_pool','video_tracks','audio_tracks','av_track_groups','styles')},
                'media':asdict(project.media)}

        def sample_frame(self,name):
            self.phase='frame sampling '+name
            from .cue_word_alignment import cue_words
            page=self.page;page.select_cue('5')
            page.video.set_paused(True);page.video.controller.set_volume(0)
            page._seek(7.425)
            yield lambda:not page.video._playback_clock.exact_seek_pending
            yield lambda:page._prepared_caption('5') is not None
            yield .3
            cue=next(cue for cue in page.project.cues if cue.id=='5')
            prepared=page._prepared_caption('5')
            words,reason=cue_words(page.project,cue)
            override=copy.deepcopy(page.project.studio_state.get('term_word_overrides',{}).get('5',{}))
            caption=getattr(prepared.snapshot,'resolved_caption',None)
            row={'cue_id':'5','requested_ms':7425,'timeline_ms':page.timeline.playhead_ms,
                'cue_text':cue.text,'prepared_text':prepared.snapshot.text,
                'resolved_caption_text':getattr(caption,'text',''),
                'word_alignment':reason,'words':[asdict(word) for word in words],
                'display_projection':override,'render_truth':page.render_truth_probe(force=True)}
            if getattr(page,'_caption_scene',None):row['caption_scene']=page._caption_scene.trace()
            self.result.setdefault('frames',{})[name]=row
            self.check('prepared caption matches current body '+name,prepared.snapshot.text==cue.text)
            if caption:self.check('resolved caption matches current body '+name,''.join(caption.text.split())==''.join(cue.text.split()))
            if override:
                self.check('derived displayed words match current body '+name,
                    ''.join(str(word['text']) for word in override.get('words',()))==cue.text,override)
                target=next((word for word in override.get('words',()) if word['text']=='autumn'),None)
                if target and self.result.get('source_name_span'):
                    self.check('canonical display retains whole original name span '+name,
                        [target['start_ms'],target['end_ms']]==self.result['source_name_span'],target)
            frame=output/(name+'-mpv.png')
            page.video.controller.screenshot_to_file(frame,mode='window')
            yield lambda:frame.is_file()
            self.result['screenshots'].append(frame.name)
            self.shot(name+'-normal-window')

        def tick(self):
            if self.busy or self.finished:return
            self.busy=True
            try:
                now=time.monotonic()
                if now-self.last_wait_record>=2:
                    state=self.wait_state();self.result['last_wait_state']=state
                    self.result['wait_history']=[*self.result.get('wait_history',()),state][-50:]
                    self.last_wait_record=now;self.write()
                if now>self.deadline:raise TimeoutError('Normal repair audit phase timed out: '+self.phase)
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                step=next(self.steps);self.waiting=step if callable(step) else now+float(step)
                self.deadline=now+(540 if plan['live'] else 90)
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:
                # Preserve the originating exception even when state sampling,
                # image capture or result persistence fails during shutdown.
                self.result['error']=traceback.format_exc()
                try:self.result['failed_wait_state']=self.wait_state()
                except Exception:
                    self.reporting_error('failure state')
                    self.result['failed_wait_state']={'phase':self.phase,'state_unavailable':True}
                try:self.shot('failure')
                except Exception:self.reporting_error('failure screenshot')
                self.finish()
            finally:self.busy=False

        def run(self):
            # STARTUP_PROJECT is a guard/input identity, not an automatic open:
            # normal Home launches only honor it with STARTUP_OPEN_STUDIO.
            self.check('normal Home visible before explicit actual open',window.isVisible())
            window.showNormal()
            self.phase='opening actual current48 through normal Home entry'
            window.open_studio_project(Path(plan['project_path']),mode='edit',source='human-approved-real-glossary-repair')
            yield lambda:project_ready(self.page,plan['project_path'])
            yield .3
            project=self.page.project
            self.check('actual current 48 identity',project.project_id==plan['project_id'] and len(project.cues)==48,
                {'project_id':project.project_id,'project_path':str(self.page.project_path),'cue_count':len(project.cues)})
            baseline={cue.id:cue.text for cue in project.cues};before=self.invariant(project)
            cue5=next(cue for cue in project.cues if cue.id=='5')
            # Raw ASR words are independent evidence even after an earlier
            # approved local pass has created a derived display projection.
            source=cue5.original_text;begin=source.find('奥特曼');offset=0;anchors=[]
            raw=next((project.asr_evidence[ref].get('words',()) for ref in cue5.evidence_refs
                if project.asr_evidence.get(ref,{}).get('words')),())
            for word in raw:
                end=offset+len(str(word['text']))
                if begin>=0 and offset<begin+3 and begin<end:anchors.append(word)
                offset=end
            if anchors:self.result['source_name_span']=[min(word['start_ms'] for word in anchors),max(word['end_ms'] for word in anchors)]
            yield from self.sample_frame('real48-before')
            self.shot('real48-original')
            self.phase='opening normal text tools'
            # The production toolbar owns entry placement and can move this
            # command into More at narrow widths. Invoke its normal public entry.
            QTimer.singleShot(0,self.page._open_find_replace)
            yield lambda:isinstance(QApplication.activeModalWidget(),FindReplaceDialog)
            dialog=QApplication.activeModalWidget();dialog.tabs.setCurrentIndex(3)
            self.check('selected real library active',plan['approved']['library_id'] in dialog._selected_library_ids())
            QTest.mouseClick(dialog.preview_button,Qt.LeftButton)
            yield .2
            self.result['initial_local_receipt']=copy.deepcopy(dialog._glossary_review_receipt)
            self.check('local preview invokes no AI',not dialog._glossary_review_receipt['ai_requested'])
            self.shot('real48-current-library-local-preview',dialog)
            for mapping in plan['approved']['mappings']:
                self.phase='confirming approved alias '+mapping['source']
                snapshot=snapshot_glossaries(window.legacy,[plan['approved']['library_id']])
                exists=any(term.confirmed and term.canonical==mapping['canonical'] and mapping['source'] in term.aliases
                    for library in snapshot.libraries for term in library.terms)
                if not exists:
                    item=next((dialog.preview.item(i) for i in range(dialog.preview.count())
                        if (dialog.preview.item(i).data(Qt.UserRole+1) or {}).get('surface')==mapping['source']),None)
                    self.check('missing alias surfaced from actual current text '+mapping['source'],item is not None)
                    dialog.preview.setCurrentItem(item)
                    QTest.mouseClick(dialog.associate_button,Qt.LeftButton)
                    yield lambda:getattr(dialog,'_association_dialog',None) is not None and dialog._association_dialog.isVisible()
                    form=dialog._association_dialog
                    self.check('alias prefilled from actual diagnostic '+mapping['source'],form.alias_edit.text()==mapping['source'])
                    self.check('canonical requires explicit confirmation',form.canonical_combo.currentText()=='')
                    form.library_combo.setCurrentIndex(form.library_combo.findData(plan['approved']['library_id']))
                    form.canonical_combo.lineEdit().setFocus()
                    QTest.keyClicks(form.canonical_combo.lineEdit(),mapping['canonical'])
                    self.shot('confirm-association-'+mapping['canonical'],form)
                    QTest.mouseClick(form.save_button,Qt.LeftButton)
                    yield lambda:not form.isVisible()
                    self.check('normal form saved exact mapping '+mapping['source'],any(term.canonical==mapping['canonical']
                        and mapping['source'] in term.aliases for library in snapshot_glossaries(window.legacy,[plan['approved']['library_id']]).libraries
                        for term in library.terms))
            snapshot=snapshot_glossaries(window.legacy,[plan['approved']['library_id']])
            self.result['current_committed_snapshot']=snapshot.to_dict()
            self.check('independent CHICHOO retained',{'CHIOCHOO','CHICHOO','autumn'}<=set(snapshot.canonical_terms))
            QTest.mouseClick(dialog.preview_button,Qt.LeftButton)
            yield .1
            if plan['live']:
                self.phase='waiting for current DeepSeek preview'
                QTest.mouseClick(dialog.terms_ai_button,Qt.LeftButton)
                yield .1
                self.check('normal AI button starts worker',dialog._glossary_review_worker is not None)
                self.shot('real48-deepseek-request-progress',dialog)
                yield lambda:dialog._glossary_review_worker is None
                self.check('real AI receipt ready',dialog._glossary_review_receipt is not None and dialog._glossary_review_receipt['ai_requested'])
                self.check('actual current provider',dialog._glossary_review_receipt['provider']['model']=='deepseek-v4-pro')
                self.check('complete AI return without fallback',dialog._glossary_review_receipt['successful_cues']==48
                    and not dialog._glossary_review_receipt['fallback_cues'],dialog._glossary_review_receipt['request_errors'])
            self.result['final_preview_receipt']=copy.deepcopy(dialog._glossary_review_receipt)
            allowed={(row['source'],row['canonical']) for row in plan['approved']['mappings']}
            for index,hit in enumerate(dialog._preview_hits):
                desired=(hit.original,hit.replacement) in allowed
                item=dialog.preview.item(index)
                if (item.checkState()==Qt.Checked)!=desired:
                    dialog.preview.setCurrentItem(item)
                    QTest.keyClick(dialog.preview,Qt.Key_Space)
                self.check('preview selection limited to approved aliases '+str(index),(item.checkState()==Qt.Checked)==desired)
            self.result['unapplied_other_ai_proposals']=[{'cue_id':hit.cue_id,'from':hit.original,'to':hit.replacement,'source':hit.source}
                for hit in dialog._preview_hits if (hit.original,hit.replacement) not in allowed]
            self.shot('real48-final-preview',dialog)
            self.check('preview leaves actual current text unchanged',{cue.id:cue.text for cue in project.cues}==baseline)
            selected=dialog._checked_hits()
            final=dict(baseline);final.update(values_from_occurrences(project,selected))
            index=self.page.undo_stack.index()
            if selected:
                QTest.mouseClick(dialog.all_button,Qt.LeftButton)
                yield .2
                self.check('apply makes one undo step',self.page.undo_stack.index()==index+1)
                self.check('checked proposals applied exactly',{cue.id:cue.text for cue in project.cues}==final)
                self.check('all original clocks/speakers/transforms/evidence retained',self.invariant(project)==before)
                self.page.undo_stack.undo()
                self.check('one undo restores actual editable baseline',{cue.id:cue.text for cue in project.cues}==baseline)
                self.page.undo_stack.redo()
                self.check('redo restores chosen final',{cue.id:cue.text for cue in project.cues}==final)
            else:self.check('zero selected disables apply',not dialog.all_button.isEnabled())
            dialog.reject();QTest.mouseClick(self.page.save_button,Qt.LeftButton)
            self.phase='saving approved actual current48'
            yield .2
            self.check('save target is exact approved actual project',Path(self.page.project_path).resolve()==Path(plan['project_path']).resolve())
            saved=load_project(plan['project_path'])
            self.check('actual saved file matches UI',{cue.id:cue.text for cue in saved.cues}==final)
            self.check('saved boundaries and original evidence retained',self.invariant(saved)==before)
            window.open_studio_project(Path(plan['project_path']),mode='edit',source='human-approved-repair-reopen')
            self.phase='reopening approved actual current48'
            yield lambda:project_ready(self.page,plan['project_path'])
            self.check('normal reopened UI retains final',{cue.id:cue.text for cue in self.page.project.cues}==final)
            self.check('cue5 displays exact approved canonical',next(cue for cue in self.page.project.cues if cue.id=='5').text=='还是在等autumn出结果')
            yield from self.sample_frame('real48-reopened')
            self.shot('real48-saved-reopened')
            artifacts=export_subtitle_artifacts(saved,output/'exports','real48-reviewed',
                SubtitleExportOptions(frozenset({'srt','ass','txt','json'}),'both'))
            projected=projected_cues(saved,domain='timeline')
            for artifact in artifacts:
                view=copy.copy(saved);view.cues=sorted([cue for cue in projected if not artifact.speaker_id or cue.speaker_id==artifact.speaker_id],
                    key=lambda cue:(cue.start_ms,cue.end_ms,cue.id))
                verified=verify_subtitle_artifact(artifact,view)
                self.check('parser verifies export '+artifact.path.name,verified.valid)
                self.result['exports'].append({'path':str(artifact.path),'format':artifact.format,'speaker_id':artifact.speaker_id,'cue_count':artifact.cue_count})
            self.result['final_cues']=[{'cue_id':cue.id,'text':cue.text,'start_ms':cue.start_ms,'end_ms':cue.end_ms,'speaker_id':cue.speaker_id} for cue in saved.cues]
            self.result['project_sha256_after']=sha_file(plan['project_path'])
            self.result['glossary_sha256_after']=sha_file(plan['glossary_path'])
            for path,digest in plan['protected'].items():self.check('readonly source preserved '+Path(path).name,sha_file(path)==digest)
            if plan['live']:
                requests=list((output/'requests').glob('*-request-body.json'))
                self.result['actual_http_request_count']=len(requests)
                self.check('actual HTTP bounded to approved budget',1<=len(requests)<=2)
            else:
                from . import blank_project_audit
                self.check('no provider call in local audit',blank_project_audit._provider_calls==0)

        def finish(self):
            if self.finished:return
            self.finished=True
            try:self.timer.stop()
            except Exception:self.reporting_error('timer stop')
            self.best_effort_write()
            def stopped():self.result['gui_shutdown']=True;self.best_effort_write()
            app=QApplication.instance()
            if app is not None:
                try:app.aboutToQuit.connect(stopped)
                except Exception:self.reporting_error('shutdown signal')
            window.result_exit_code=0 if self.result['passed'] else 1
            # A failed audit must terminate even if closing opens a dirty guard.
            # Exit only ends this opted-in audit process; it does not save data.
            if not self.result['passed'] and app is not None:
                try:QTimer.singleShot(0,lambda:app.exit(1))
                except Exception:self.reporting_error('shutdown fallback')
            try:window.close()
            except Exception:
                self.reporting_error('window close');self.best_effort_write()
                if app is not None:app.exit(window.result_exit_code)

    window._acceptance_audit=Audit()
