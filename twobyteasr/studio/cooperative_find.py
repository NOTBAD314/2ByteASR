"""GUI-owned immutable text snapshots, computed in bounded event-loop slices.

No worker touches a mutable project or widget. Ordinary Python matching and
row preparation yield every 6ms, avoiding a CPU thread competing for the GIL.
"""
from collections import Counter
from time import perf_counter
from PySide6.QtCore import QTimer, Qt
from ..diagnostics.text_work import TextWork, count
from ..i18n import bind_text, tr
from .subtitle_text_targets import iter_text_entries, scope_entries
from .studio_text_tools import match_text_entries, _compile_needle, SCOPE_ALL
from .text_search_snapshot import TextSnapshot, text_key


class CooperativeFind:
    SEARCH_BUDGET_S = .006

    def _scope_query_key(self):
        if self._current_scope() == SCOPE_ALL:return ()
        page=self._page
        timeline=getattr(page,'timeline',None)
        return (page.session.selected_cue_id, tuple(page.selected_cue_ids()),
            getattr(timeline,'active_subtitle_layer',''),tuple(getattr(timeline,'translation_selected_ids',())),
            getattr(page,'_playhead_ms',getattr(page,'playhead_ms',0)) if self._current_scope() == 'range' else None)

    def cancel_text_search(self):
        self._search_generation=getattr(self,'_search_generation',0)+1
        timer=getattr(self,'_slice_timer',None)
        if timer is not None:timer.stop()
        self._search_iterator=None
        self._search_pending=False
        job=getattr(self,'_regex_job',None)
        if job is not None:job['cancel'].set()
        work=getattr(self,'_search_work',None)
        if work is not None:
            self._last_search_metrics=work.finish('cancelled')
            self._search_work=None

    def start_text_search(self, *, action=None):
        self.cancel_text_search()
        self._search_timer.stop()
        self._preview_binding=None
        project=self._page.session.project
        if project is None:return
        if getattr(self,'_search_project',getattr(self.text_targets,'_project',None)) is not project:
            self._text_snapshot=None
            self.text_targets.bind(project,self._page)
        self._search_project=project
        self._preview_snapshot_digest=None
        self._glossary_review_receipt=None
        self._search_pending=True
        self._search_work=TextWork('cue.search')
        self._search_iterator=self._search_steps(project,self._query(),action)
        if not hasattr(self,'_slice_timer'):
            self._slice_timer=QTimer(self)
            self._slice_timer.setSingleShot(True)
            self._slice_timer.timeout.connect(self._run_search_slice)
        self._refresh_status()
        self._slice_timer.setInterval(0)
        self._slice_timer.start(0)

    def _run_search_slice(self):
        work=self._search_work
        if work is None:return
        try:
            with work.activate():next(self._search_iterator)
        except StopIteration:
            return
        except Exception as exc:
            self._last_search_metrics=work.finish('failed')
            self._search_work=None
            self._search_pending=False
            self._preview_binding=None
            self.status_label.setText(tr('查找失败：{reason}',reason=str(exc)[:200]))
            return
        if self._search_pending:self._slice_timer.start()

    def _search_steps(self,project,query,action):
        from .studio_find_replace import TextReplaceBinding, _locked_ids, _preview_colors
        work=self._search_work
        generation=self._search_generation
        mode=self.text_targets.mode_value()
        tracks=self.text_targets.tracks()
        if project is not self._page.session.project or self._query()!=query:
            self.cancel_text_search();self._queue_live_search();return
        with work.activate('fingerprint'):
            key=text_key(project,mode=mode,tracks=tracks)
        cached=getattr(self,'_text_snapshot',None)
        if cached is not None and cached.key == key:
            snapshot=cached
            count('text_snapshot_cache_hits')
        else:
            work.calls['iter_text_entries']+=1
            # Capture this lightweight text projection in the same GUI turn
            # as its key/scope. Yielding halfway through reading live rows
            # could otherwise mix an unversioned edit and its later rollback.
            # Matching and all result preparation below remain budgeted.
            with work.activate('snapshot'):
                entries=tuple(iter_text_entries(project,mode=mode,tracks=tracks))
            snapshot=TextSnapshot(key,entries,mode,tuple(sorted(tracks)) if tracks is not None else None)
            self._text_snapshot=snapshot
        self.text_targets._count=len(snapshot.entries)
        self.text_targets._count_ready=True
        self._update_target_summary()
        with work.activate('scope'):
            entries=scope_entries(self._page,self._current_scope(),entries=snapshot.entries)
            lookup=snapshot.lookup
            locked=set(_locked_ids(self._page)) | {c.id for c in project.cues if getattr(c,'locked',False)} if self.lock_box.isChecked() else set()
            try:pattern=_compile_needle(query[0],case_sensitive=query[3],whole_word=query[4],regex=query[5])
            except Exception:pattern=None
        yield
        hits=[]
        if query[0].strip() and pattern is not None and query[5]:
            from .regex_search_job import start_regex_job
            previous=getattr(self,'_regex_job',None)
            while previous is not None and previous['thread'].is_alive():
                self._slice_timer.setInterval(16)
                yield
            job=self._regex_job=start_regex_job(tuple(entries),query,locked)
            self._slice_timer.setInterval(16)
            while job['thread'].is_alive():
                yield
            self._slice_timer.setInterval(0)
            if job.get('error'):raise RuntimeError(job['error'])
            hits=job.get('hits',[])
            self._regex_job=None
            count('regex_process_jobs')
            count('matched_entries_scanned',len(entries))
        elif query[0].strip() and pattern is not None:
            deadline=perf_counter()+self.SEARCH_BUDGET_S
            for offset in range(0,len(entries),64):
                with work.activate('matching'):
                    hits.extend(match_text_entries(entries[offset:offset+64],pattern,query[1],regex=query[5],body_only=query[6],locked_ids=locked))
                    count('matched_entries_scanned',len(entries[offset:offset+64]))
                if perf_counter()>=deadline:
                    yield
                    deadline=perf_counter()+self.SEARCH_BUDGET_S
        # Compare exact inputs again: revisions alone do not catch every
        # importer/direct assignment. An old project/query cannot publish.
        with work.activate('publish_validation'):
            valid=(generation==self._search_generation and project is self._page.session.project
                and self._query()==query and text_key(project,mode=mode,tracks=tracks)==key)
        if not valid:
            self.cancel_text_search()
            self._queue_live_search()
            return
        self._entry_by_key=lookup
        self._preview_hits=[]
        self._applied_rows.clear()
        self.preview.clear()
        texts={key:entry.text for key,entry in lookup.items()}
        colors=_preview_colors() if hits else {}
        pending=[]
        deadline=perf_counter()+self.SEARCH_BUDGET_S
        for item in self._iter_preview_items(hits,texts,colors):
            pending.append(item)
            if perf_counter()>=deadline:
                with work.activate('result_fill'):self.preview.append_items(pending)
                pending=[]
                yield
                deadline=perf_counter()+self.SEARCH_BUDGET_S
        with work.activate('result_fill'):self.preview.append_items(pending)
        # A mutation can also arrive while a large list is filling.
        if (project is not self._page.session.project or self._query()!=query
                or text_key(project,mode=mode,tracks=tracks)!=key):
            self.cancel_text_search();self._queue_live_search();return
        self._preview_hits=hits
        self._preview_query=query
        self._preview_binding=TextReplaceBinding.capture(project,snapshot=snapshot)
        self._search_pending=False
        self._search_work=None
        self._search_iterator=None
        self._refresh_status()
        skipped=getattr(self,'_restore_skipped',None)
        self._restore_skipped=None
        if skipped and Counter(h.target_key for h in hits)==skipped:self._set_all_preview_checked(False)
        self._last_search_metrics=work.finish()
        if action:QTimer.singleShot(0,lambda:self._run_search_action(generation,project,query,action))

    def _run_search_action(self,generation,project,query,action):
        if (generation!=self._search_generation or project is not self._page.session.project
                or self._query()!=query or self._preview_binding is None):return
        if action=='apply':self._do_apply_preview()
        elif action=='next':self._replace_next_ready()

    def hideEvent(self,event):
        self.cancel_text_search()
        super().hideEvent(event)

    def _preview_item_clicked(self,item):
        if getattr(self,'_search_pending',False) or self._preview_binding is None:return
        from .subtitle_text_targets import navigate_target
        target=item.data(Qt.UserRole+3)
        if target is not None and self._preview_binding.matches(self._page.session.project):
            navigate_target(self._page,target)
