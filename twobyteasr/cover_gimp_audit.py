"""Opt-in real Studio + GIMP document audit. Native mouse/IME QA is separate."""
import hashlib,json,os,time,traceback,uuid
from pathlib import Path
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from .studio_acceptance_audit import require


def offline_evidence():
    import ctypes,_socket
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32;adv=ctypes.windll.advapi32
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    adv.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    handle=wintypes.HANDLE();adv.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(handle))
    value=wintypes.DWORD();size=wintypes.DWORD();ok=adv.GetTokenInformation(handle,29,ctypes.byref(value),4,ctypes.byref(size))
    kernel.CloseHandle(handle)
    result=dict(pid=os.getpid(),appcontainer=value.value if ok else None,network={})
    for host in ('1.1.1.1','140.82.114.4'):
        sock=_socket.socket();sock.settimeout(2)
        try:sock.connect((host,443));result['network'][host]='connected'
        except OSError as exc:result['network'][host]=getattr(exc,'winerror',None)
        finally:sock.close()
    return result


def start(window,out):
    def run():
        from .build_identity import load_build_identity
        from .cover_psd import psd_metadata
        from .cover_samples import demo_character
        from .cover_templates_ui import TemplatePicker
        from PIL import Image
        report=dict(passed=False,checks={},build=load_build_identity().to_dict(),metrics=[],native_mouse_verified=False)
        page=window.studio_page;work=None;begun=time.perf_counter()
        def pump(seconds=.03):
            until=time.monotonic()+seconds
            while time.monotonic()<until:QApplication.processEvents();time.sleep(.004)
        def wait(predicate,timeout=120):
            deadline=time.monotonic()+timeout
            while not predicate() and time.monotonic()<deadline:pump()
            require(predicate(),'等待超时：'+(work.status.text() if work else 'Studio'))
        def check(name,value):
            report['checks'][name]=bool(value)
            (out/'cover-gimp-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            require(value,name)
        def request(op,key,**payload):
            result=[];error=[];work.session.request(op,key,result.append,error.append,**payload)
            wait(lambda:result or error)
            require(not error,error[0] if error else '')
            return result[0]
        def idle():wait(lambda:not work.session.pending and not work.session.queue and not work.jobs)
        def document():return work.current
        try:
            wait(lambda:page.project is not None and getattr(page.project,'media',None) is not None)
            before=page.project.to_dict();page.timeline.set_playhead(8250);page.video.set_paused(True)
            QTest.mouseClick(page.make_cover_button,Qt.LeftButton)
            wait(lambda:page.cover_controller.editor is not None)
            work=page.cover_controller.editor
            wait(lambda:work.session.is_ready and bool(work.documents));idle()
            first=document();state=request('describe',first)
            if os.environ.get('TWOBYTEASR_COVER_OFFLINE_AUDIT')=='1':
                report['offline']={'host':offline_evidence(),'gimp_plugin':request('offline-evidence',first)}
                check('actual_process_network_isolation',all(v['appcontainer']==1 and set(v['network'].values())=={10013} for v in report['offline'].values()))
            report['gimp_session']=str(work.session.root)
            report['metrics'].append(dict(action='studio-frame-to-editable-gimp',seconds=time.perf_counter()-begun))
            check('studio_frame_unlocked_live_layer',len(state['layers'])==1 and not state['layers'][0]['position_locked'] and page.cover_controller.last_receipt is not None)
            work.quick.setPlainText('本地中文标题\n第二行仍可编辑');work.add_text();idle()
            state=request('describe',first);title=next(l for l in state['layers'] if l['text'] is not None)
            check('editable_chinese_multiline_font',title['text']=='本地中文标题\n第二行仍可编辑' and 'Heavy' in title['font'])
            staged=work.session.stage(demo_character(),'.png');request('add-image',first,file=staged,name='透明人物测试')
            saved=[];errors=[]
            work.session.save(first,out/'中文路径封面.xcf',saved.append,errors.append);wait(lambda:saved or errors)
            check('atomic_save_ack_and_native_clean',bool(saved) and saved[0]['clean'] and not request('describe',first)['dirty'])
            request('title',first,slot=title['id'],text='修改后标题\n只改变第一文档')
            digest=hashlib.sha256((out/'中文路径封面.xcf').read_bytes()).hexdigest()
            bad=out/'不可写目标.xcf';bad.mkdir();failed=[]
            work.session.save(first,bad,lambda _:failed.append('unexpected success'),failed.append);wait(lambda:failed)
            check('write_failure_retains_previous_and_dirty',failed!=['unexpected success'] and hashlib.sha256((out/'中文路径封面.xcf').read_bytes()).hexdigest()==digest and request('describe',first)['dirty'])
            saved=[];work.session.save(first,out/'中文路径封面.xcf',saved.append,errors.append);wait(lambda:saved or errors)
            check('retry_save_succeeds',bool(saved) and saved[0]['clean'])
            for fmt in ('png','jpg','psd'):
                target=out/('当前帧封面.'+fmt);value=request('export',first,format=fmt,output='outputs/audit-'+uuid.uuid4().hex+'.'+fmt)
                target.write_bytes(work.session.output_bytes(value))
                if fmt!='psd':check(fmt+'_dimensions',Image.open(target).size==(state['width'],state['height']))
            psd=psd_metadata(out/'当前帧封面.psd');report['psd']=psd
            check('psd_raster_text_boundary_reported',not any(l.get('text') for l in psd['layers']) and len(psd['layers'])>=3)
            entries=work.library.entries();check('legacy_templates_present',len(entries)>=2)
            samples=[]
            for number,entry in enumerate(entries[:2],1):
                original=work.library.asset(entry,'xcf' if entry.get('xcf') else 'psd').read_bytes();original_hash=hashlib.sha256(original).hexdigest()
                entry['favorite']=True;work.library.metadata(entry)
                previous=set(work.documents);work.apply_template(entry,False)
                wait(lambda:len(set(work.documents)-previous)==1);idle();key=document()
                st=request('describe',key);meta=work.session.meta[key]
                check(f'template_{number}_editable_slots',bool(meta['slots'].get('background')) and any(l['id']==meta['slots'].get('title') and l['text'] is not None for l in st['layers']))
                # Explicitly migrate/update the private test master, then verify an
                # ordinary instance edit/save does not modify that generation.
                migrated=[];work.save_template(key,entry['name'],entry['id'],migrated.append);wait(lambda:migrated);idle()
                native=migrated[0];xcf=work.library.asset(native,'xcf');thumb=work.library.asset(native,'thumbnail')
                (out/f'sample-{number}.xcf').write_bytes(xcf.read_bytes());(out/f'sample-{number}.png').write_bytes(thumb.read_bytes())
                check(f'template_{number}_favorite_preserved',native['favorite'])
                check(f'template_{number}_old_asset_preserved',hashlib.sha256(original).hexdigest()==original_hash and work.library.asset(entry,'xcf' if entry.get('xcf') else 'psd').read_bytes()==original)
                master=hashlib.sha256(xcf.read_bytes()).hexdigest()
                work.replace_frame(key=key);idle();request('title',key,slot=meta['slots']['title'],text='新截图 · 新标题\n模板构图保留')
                save=[];work.session.save(key,out/f'实例-{number}.xcf',save.append,errors.append);wait(lambda:save or errors)
                check(f'template_{number}_master_unchanged',hashlib.sha256(xcf.read_bytes()).hexdigest()==master)
                samples.append(dict(entry=native,document=key,source_sha256=original_hash))
            report['samples']=samples
            check('two_document_save_no_crosswrite',request('describe',first)['layers'][1]['name']!='' and request('describe',first)['file']==str(out/'中文路径封面.xcf'))
            previous=set(work.documents);work.open_document(out/'中文路径封面.xcf');wait(lambda:len(set(work.documents)-previous)==1);idle()
            reopened=document();st=request('describe',reopened)
            text=next(l for l in st['layers'] if l['text'] is not None)
            check('xcf_reopen_editable_title_and_alpha_layer',text['text']=='修改后标题\n只改变第一文档' and len(st['layers'])==3)
            request('title',reopened,slot=text['id'],text='XCF 重开后再次修改')
            native=request('describe',reopened);work.accept_state(native)
            check('xcf_reopen_modify',next(l for l in native['layers'] if l['id']==text['id'])['text']=='XCF 重开后再次修改')
            check('native_title_syncs_to_workbench',work.quick.toPlainText()=='XCF 重开后再次修改')
            work.quick.setPlainText('工作台尚未应用的输入')
            work.accept_state(request('title',reopened,slot=text['id'],text='原生窗口再次修改'))
            work.choose(first);work.choose(reopened)
            check('pending_title_survives_native_update_and_document_switch',work.quick.toPlainText()=='工作台尚未应用的输入')
            work.change_title();idle()
            work.accept_state(request('title',reopened,slot=text['id'],text='提交后恢复原生同步'))
            check('applied_title_resumes_native_sync',work.quick.toPlainText()=='提交后恢复原生同步')
            work.show();work.raise_();work.refresh_preview();idle();pump(.3);work.grab().save(str(out/'workbench.png'))
            picker=TemplatePicker(work.library,work.settings,work);picker.show();pump(.3);picker.grab().save(str(out/'templates.png'));picker.close()
            work.hide();pump(.2)
            check('studio_project_preserved',page.project.to_dict()==before)
            if os.environ.get('TWOBYTEASR_COVER_STUDIO_REGRESSION')=='1':
                frames=out/'frames';frames.mkdir(exist_ok=True)
                page.frame_capture.settings.setValue('frame_export/directory',str(frames))
                page.frame_capture.settings.setValue('frame_export/subtitles',True)
                page._seek(8.25);page.frame_capture.last=None
                QTest.mouseClick(page.save_frame_button,Qt.LeftButton);wait(lambda:not page.frame_capture.busy)
                receipt=page.frame_capture.last;report['return_frame']=receipt
                check('studio_return_original_resolution_frame',receipt and receipt['width']==page.project.media.width and abs(receipt['milliseconds']-8250)<70)
                page._toggle_playback();pump(1.3);page.video.set_paused(True)
                check('studio_return_playback',page.timeline.playhead_ms>8500)
                from .project_range import set_range
                # Exercise the independent HTML subtitle renderer after excluding
                # Photopea's QtWebEngine; only this private audit project changes.
                from .web_theme import import_theme_archive
                theme=import_theme_archive(Path(__file__).resolve().parents[1]/'assets/themes/Balatro_Dealer_Press.2byte-theme')
                page.project.style_recipes['cover-return-html']=dict(name=theme['name'],engine='remotion',webTheme=theme)
                selected=[cue for cue in page.project.cues if cue.start_ms<10000 and cue.end_ms>7500]
                require(bool(selected),'短片范围没有字幕可验收')
                for cue in selected:cue.style_id='cover-return-html'
                report['return_html_theme']=theme['name']
                set_range(page.project,7500,10000)
                QTest.mouseClick(page.studio_render_button,Qt.LeftButton);wait(lambda:page.export_workspace is not None)
                ui=page.export_workspace;pump(.3);(out/'video').mkdir(exist_ok=True)
                ui.directory.setText(str(out/'video'));ui.filename.setText('cover-return-range')
                ui.filename_prefix.clear();ui.filename_suffix.clear();ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
                if ui.encoder.findData('libx264')<0:ui.encoder.addItem('Software x264','libx264')
                ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'));started=time.perf_counter()
                QTest.mouseClick(ui.export_button,Qt.LeftButton);wait(lambda:ui._last_job is not None);wait(lambda:not ui._running,160)
                check('studio_return_io_range_export',ui.pages.currentWidget()==ui.success_page)
                report['video_export']=dict(path=ui._last_job.output_path,seconds=time.perf_counter()-started,metadata=ui._last_job.completion_metadata)
                window.grab().save(str(out/'studio-return.png'));page.undo_stack.setClean()
            import psutil
            process=psutil.Process()
            report['memory']=dict(host_rss=process.memory_info().rss,children=[dict(name=p.name(),rss=p.memory_info().rss) for p in process.children(recursive=True)])
            report['metrics']+=work.session.metrics
            report['passed']=True
        except Exception:report['error']=traceback.format_exc()
        finally:
            report['seconds']=time.perf_counter()-begun
            (out/'cover-gimp.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            if os.environ.get('TWOBYTEASR_COVER_KEEP_OPEN')!='1':QApplication.quit()
    QTimer.singleShot(1800,run)
