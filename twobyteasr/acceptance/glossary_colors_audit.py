"""Opt-in normal-window acceptance for glossary filters and complete effect paints."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from . import real_long_project_audit
    real_long_project_audit.start(window, output)
    audit=window._real_long_project_audit
    audit.sequence=run(audit,window,Path(output))
    finish=audit.finish
    def finished():
        if audit.error:
            try:
                from .blank_project_audit import _capture
                _capture(window,Path(output)/'failure-window.png')
            except Exception: pass
        finish()
    audit.finish=finished


def run(a,window,out):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QColor, QFontMetrics, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea, QStyle, QStyleOptionTab
    from ..design.theme_manager import apply_application_theme
    from ..caption_style.scoped_style import effective_layer_recipe
    from ..caption_style.caption_layer_transform import displayed_layer
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..caption_style.style_presets import StylePresetStore
    from ..projects.studio_project import save_project
    from ..timeline.selection_scope import SelectionScope
    from .blank_project_audit import _capture
    app=QApplication.instance()
    restoring=os.environ.get('GLOSSARY_COLORS_RESTORE')=='1'
    prefix='restart' if restoring else 'first'
    old=json.loads((out/'first-result.json').read_text('utf8')) if restoring else None
    apply_application_theme(app,'warm')
    window.resize(1440,900)
    window.open_studio_project(str(a.project_path))
    yield a.wait(a.ready,'normal Studio ready',110)
    a.page=p=window.built_page('studio')
    p.video.set_paused(True);p.volume_slider.setValue(0)
    a.result['dpr']=window.devicePixelRatioF()
    a.result['platform']=app.platformName()
    a.result['phase_kind']=prefix
    a.check('normal Windows platform',app.platformName()=='windows')
    if os.environ.get('GLOSSARY_COLORS_LAYOUT_ONLY')=='1':
        from .inspector_layout_audit import run as layout_run
        yield from layout_run(a,window,out)
        return
    if os.environ.get('GLOSSARY_COLORS_EYEDROP_ONLY')=='1':
        yield from eyedrop_suite(a,window,out)
        return
    a.set_phase('glossary')
    window._manage_terms()
    yield .3
    page=window.term_library_page._ensure_library()
    legacy=window.legacy
    game='洛克王国：世界'
    page.add_game_item(game,select=True)
    yield .3
    page.refresh_current_game()
    yield .2
    a.check('current library selected',page.state['game']==game)
    from PySide6.QtWidgets import QAbstractButton
    a.check('per-item learning entry removed',not hasattr(page,'learning_toggle') and not any(b.text()=='逐条确认' for b in page.findChildren(QAbstractButton)))
    store=Path(legacy.LEARNED_TERMS_PATH)
    a.check('glossary storage isolated',store.resolve().is_relative_to(out))
    a.result['glossary_store']=str(store)
    if not restoring:
        initial=[r for r in page._unified_term_rows() if r['status']=='reference']
        a.check('complete real builtin library',len(initial)>200)
        hidden=initial[0]['target']
        legacy.set_reference_terms_hidden(game,[hidden],True)
        legacy.add_learned_mapping(page._library_key(),'统计哨兵','统计哨兵',category='游戏术语')
        legacy.add_learned_mapping(page._library_key(),'哨兵听成','统计哨兵',category='游戏术语')
        other=legacy.create_learned_content('其他库保护验收','game',create_new=True)
        legacy.add_learned_mapping(other,'其他词','其他词')
        page.add_game_item('其他库保护验收',library_id=other)
        for i in range(page._learning_store.threshold):
            page._learning_store.record_manual_edit('星见鸦','星见雅',project='独立验收',token='glossary-colors-'+str(i))
        learning=copy.deepcopy(page._learning_store.load())
        other_rows=legacy.learned_mappings_for_game(other)
        a.check('pending learning fixture exists',bool(page._learning_store.pending()))
        page._notify_library_changed();page.refresh_current_game()
        yield .2
        refs=[r for r in page._unified_term_rows() if r['status']=='reference']
        reference_count=len(refs)
        alias_ref=next((r for r in reversed(refs) if (r.get('reference') or {}).get('aliases')),refs[-1])
        alias=((alias_ref.get('reference') or {}).get('aliases') or [alias_ref['target']])[0]
        page.status_buttons['confirmed'].click();page.search.setText('哨兵听成')
        yield .1
        a.check('heard spelling search finds canonical card',page._term_model.rowCount()==1 and page._term_model.data_for_row(0)['target']=='统计哨兵')
        edits=[];page.listing.edit_requested.connect(lambda *_:edits.append(True))
        index=page._term_model.index(0,0)
        rect=page.listing.card_delegate.category_rect(page.listing.visualRect(index),index,page.listing.font())
        QTest.mouseClick(page.listing.viewport(),Qt.LeftButton,pos=rect.center())
        yield .1
        a.check('category badge independent from edit',page.filter_category.currentData()=='游戏术语' and not edits)
        a.check('all category reset entry',page.filter_category.findData('')==0)
        page.search.clear();page.status_buttons['reference'].click()
        page._choose_category_filter(alias_ref['category']);page.search.setText(alias)
        yield .1
        shown=[page._term_model.data_for_row(i) for i in range(page._term_model.rowCount())]
        a.check('status category keyword intersection',bool(shown) and all(r['status']=='reference' and r['category']==alias_ref['category'] for r in shown) and alias_ref['target'] in [r['target'] for r in shown])
        a.check('bulk count ignores filters',str(reference_count) in page.confirm_all_button.text() and len(shown)<reference_count)
        a.result['glossary_toolbar_layouts']=[]
        for size in ((1280,800),(1440,900),(1920,1080)):
            window.resize(*size);yield .5
            a.result.setdefault('card_layouts',[]).append(dict(size=size,columns=page.listing.columns(),viewport=page.listing.viewport().size().toTuple(),sidebar=page.library_sidebar.width()))
            a.check('six uniform cards '+str(size),page.listing.columns()==6)
            controls=(page.search,page.filter_category,page.confirm_all_button,page.ai_menu_button,page.import_terms)
            a.result['glossary_toolbar_layouts'].append(dict(size=size,page=list(page.size().toTuple()),narrow=page._term_toolbar_narrow,controls=[dict(name=w.objectName(),pos=list(w.mapTo(page,QPoint()).toTuple()),size=list(w.size().toTuple())) for w in controls]))
            pair=page.term_filter_pair
            a.result.setdefault('filter_row_geometry',[]).append(dict(size=size,pair=list(pair.geometry().getRect()),status=list(page.status_segment.geometry().getRect()),search=list(page.search.geometry().getRect()),category=list(page.filter_category.geometry().getRect()),pair_min=list(pair.minimumSizeHint().toTuple())))
            a.check('search and category do not overlap '+str(size),not page.search.geometry().intersects(page.filter_category.geometry()))
            a.check('filter children fit their row '+str(size),all(pair.rect().contains(w.geometry()) for w in (page.search,page.filter_category)))
            a.check('filter pair does not overlap status '+str(size),not pair.geometry().intersects(page.status_segment.geometry()) if pair.parentWidget()==page.status_segment.parentWidget() else True)
            _capture(window,out/('glossary-'+str(size[0])+'.png'))
            a.check('compact toolbar inside main area '+str(size),all(w.isVisible() and page.rect().contains(w.mapTo(page,QPoint(0,0))) and page.rect().contains(w.mapTo(page,w.rect().bottomRight())) for w in controls))
        window.resize(1440,900);yield .1
        _capture(window,out/'glossary-filtered.png')
        writes=[];atomic=legacy.atomic_write_json
        def counted(path,*args,**kwargs):
            if Path(path)==store:writes.append(str(path))
            return atomic(path,*args,**kwargs)
        legacy.atomic_write_json=counted
        try:
            QTest.mouseClick(page.confirm_all_button,Qt.LeftButton)
            a.check('busy prevents duplicate confirmation',not page.confirm_all_button.isEnabled())
            page.confirm_all_references()
            yield a.wait(lambda:not page._confirming_references,'whole library confirmation',30)
        finally:legacy.atomic_write_json=atomic
        a.check('one atomic library save',len(writes)==1)
        a.check('all references confirmed despite filter',page._card_stats['reference']==0 and page._card_stats['hidden']==1)
        a.check('filtered reference view immediately empty',page._term_model.rowCount()==0)
        a.check('other library untouched',legacy.learned_mappings_for_game(other)==other_rows)
        a.check('pending learning unchanged',page._learning_store.load()==learning)
        a.check('no reference button disabled',not page.confirm_all_button.isEnabled())
        canonical=legacy.user_confirmed_mappings_for_game(page._library_key())
        aliases=(alias_ref.get('reference') or {}).get('aliases') or []
        a.check('confirmed aliases preserved',all(any(r['from']==alias and r['to']==alias_ref['target'] for r in canonical) for alias in aliases if alias!=alias_ref['target']))
        page.search.clear();page._choose_category_filter('');page.status_buttons[''].click();yield .1
        a.result['glossary']=dict(stats=page._card_stats,confirmed_count=reference_count,library_id=page._library_key(),hidden=hidden,alias_target=alias_ref['target'])
    else:
        page.search.clear();page._choose_category_filter('');page.status_buttons[''].click();yield .1
        a.check('new process restores confirmation and hidden state',page._card_stats==old['glossary']['stats'])
        a.check('new process has disabled bulk action',not page.confirm_all_button.isEnabled())
        a.check('new process has pending learning',bool(page._learning_store.pending()))
        a.result['glossary']=old['glossary']
    stats=page._card_stats
    row=page.game_list.itemWidget(page.game_list.currentItem())
    a.check('sidebar title tabs count same canonical cards',page._game_term_count(game,page._library_key())==stats['confirmed'] and page._game_reference_count(game,page._library_key())==stats['reference'] and str(stats['confirmed']) in row.count_label.text() and str(stats['confirmed']) in page.selected_stats.text())
    _capture(window,out/(prefix+'-glossary-complete.png'))
    a.result['glossary_sha256']=hashlib.sha256(store.read_bytes()).hexdigest()
    if restoring:a.check('restart leaves glossary bytes intact',a.result['glossary_sha256']==old['glossary_sha256'])
    # Return to the normal Studio through its project entry.
    window.open_studio_project(str(a.project_path))
    yield a.wait(a.ready,'return to Studio',60)
    a.page=p=window.built_page('studio');p.video.set_paused(True);p.volume_slider.setValue(0)
    p._set_major_panel_visible('context',True);p.context_drawer.setCurrentIndex(1)
    p.select_cue(p.project.cues[0].id)
    p.cue_controller.apply_selection_scope(SelectionScope.explicit([p.project.cues[0].id],p.project.cues[0].id))
    p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
    yield .2
    a.set_phase('tool-tabs')
    names=('AI设计','样式','动效','视频','剪辑助手','素材')
    layouts=[]
    for size in ((1280,800),(1440,900),(1920,1080)):
        window.resize(*size)
        for requested in (280,360,550):
            total=max(1000,p.upper_splitter.width())
            p.upper_splitter.setSizes([280,max(300,total-280-requested),requested])
            p._update_context_tab_labels();yield .12
            selector=p.context_tools
            a.check('all full labels '+str(size)+str(requested),tuple(b.text() for b in selector.buttons)==names)
            a.check('uniform icon size '+str(size)+str(requested),not any(b.icon().isNull() for b in selector.buttons))
            for i,button in enumerate(selector.buttons):
                rect=button.rect()
                # 2026-11-09 redesign: icon above the label, so the label alone sets the width.
                required=max(QFontMetrics(button.font()).horizontalAdvance(button.text()),button.iconSize().width())+8
                a.check('full tab width '+str(size)+str(requested)+str(i),button.width()>=required and selector.rect().contains(button.geometry()))
                for x in (12,rect.center().x(),rect.right()-5):
                    p.context_drawer.setCurrentIndex((i+1)%6)
                    QTest.mouseClick(button,Qt.LeftButton,pos=QPoint(x,rect.center().y()))
                    a.check('whole tab hit '+str(size)+str(requested)+str(i)+str(x),p.context_drawer.currentIndex()==i and button.isChecked())
            layouts.append(dict(window=list(window.size().toTuple()),drawer=p.context_drawer.width(),dpr=window.devicePixelRatioF(),columns=selector._columns,buttons=[b.geometry().getRect() for b in selector.buttons]))
    a.result['tab_layouts']=layouts
    window.resize(1440,900);p.upper_splitter.setSizes([280,700,440]);p.context_drawer.setCurrentIndex(1);yield .2
    p.context_panel.grab().save(str(out/(prefix+'-tool-panel.png')))
    a.set_phase('colors')
    def state(layer):
        cue=p.project.cues[0]
        shown=displayed_layer(p.project,cue,layer) or cue
        snap=build_visual_cue_snapshot(p.project,shown.id,resolved_cue=shown)
        return dict(paints=snap.style_recipe.get('colors',{}).get('effectPaints',{}),fill=snap.fill,pixel_hash=snap.pixel_hash())
    if restoring:
        for layer in ('original','translation'):
            a.check(layer+' saved gradients after process restart',state(layer)==old['colors'][layer])
        _capture(window,out/'restart-colors.png')
        return
    fields=(('fill','style_fill_color'),('outline','style_outline_color'),('outline2','style_outline2_color'),('background','style_back_color'),('shadow','style_shadow_color'),('glow','style_glow_color'))
    color_pairs={'fill':('#FFFFDD44','#FFFF7755'),'outline':('#FF00DDFF','#FF1177FF'),'outline2':('#FFC255FF','#FF7733CC'),'background':('#CC224477','#CC4477AA'),'shadow':('#FFEE3355','#FF991144'),'glow':('#FF22EE66','#FF44AA55')}
    def dialog_edit(target,attribute,mode,cancel=False):
        result={};a.timer.stop()
        before=p.undo_stack.index()
        def drive():
            dialog=QApplication.activeModalWidget()
            if dialog is None:QTimer.singleShot(30,drive);return
            try:
                a.check(target+' complete shared picker mode '+str(mode),type(dialog).__name__=='FillEditorDialog' and len(dialog.mode_group.buttons())==3)
                QTest.mouseClick(dialog.mode_segment.button(mode),Qt.LeftButton)
                if mode:
                    first,second=color_pairs[target]
                    dialog.gradient.set_value(dict(type='linear-gradient',angle=45,stops=[dict(color=first,position=0),dict(color=second,position=1)]))
                    dialog._select_gradient_stop(0)
                    if mode==1:QTest.mouseClick(dialog._angle_chips[1],Qt.LeftButton)
                    else:dialog.radius_spin.setValue(135)
                else:
                    dialog.picker.hex_edit.setFocus();QTest.keyClick(dialog.picker.hex_edit,Qt.Key_A,Qt.ControlModifier)
                    QTest.keyClicks(dialog.picker.hex_edit,color_pairs[target][0][-6:]);QTest.keyClick(dialog.picker.hex_edit,Qt.Key_Tab)
                    dialog.picker.alpha_spin.setValue(85)
                value=copy.deepcopy(dialog._current_value())
                for backdrop,rect in zip(dialog.preview.BACKDROPS,dialog.preview._dot_rects()):
                    QTest.mouseClick(dialog.preview,Qt.LeftButton,pos=rect.center().toPoint())
                    a.check(target+' preview backdrop '+str(mode)+backdrop,dialog.preview.backdrop==backdrop and dialog._current_value()==value)
                a.check(target+' no project mutation before OK '+str(mode),p.undo_stack.index()==before)
                def finish():
                    try:
                        if mode==2 and not cancel:
                            base=window.grab();paint=QPainter(base);point=window.mapFromGlobal(dialog.mapToGlobal(QPoint(0,0)));paint.drawPixmap(point,dialog.grab());paint.end();base.save(str(out/('picker-'+target+'.png')))
                        result['value']=dialog._current_value()
                        if cancel:dialog.reject()
                        else:dialog.accept()
                    except Exception:result['error']=traceback.format_exc();dialog.reject()
                QTimer.singleShot(120,finish)
            except Exception:result['error']=traceback.format_exc();dialog.reject()
        QTimer.singleShot(60,drive)
        try:
            # Execute the real swatch action, including the modal exec and commit path.
            editor=getattr(p,attribute)
            button=p.style_fill_button if target=='fill' else p.style_back_button if target=='background' else getattr(p,'style_'+target+'_swatch').findChild(p._style_color_button_type())
            scroll=button.parentWidget()
            while scroll is not None and not isinstance(scroll,QScrollArea):scroll=scroll.parentWidget()
            if scroll is not None:scroll.ensureWidgetVisible(button)
            QTest.mouseClick(button,Qt.LeftButton)
        finally:a.timer.start()
        if result.get('error'):raise RuntimeError(result['error'])
        a.check(target+' commit count '+str(mode)+str(cancel),p.undo_stack.index()==before+(0 if cancel else 1))
        return result
    for target,attribute in fields:
        for mode in (0,1,2):
            dialog_edit(target,attribute,mode);yield .1
        before=state('original')
        dialog_edit(target,attribute,1,cancel=True);yield .08
        a.check(target+' cancel preserves gradient',state('original')==before)
    a.check('all effect gradients in original',set(state('original')['paints'])=={'outline','outline2','background','shadow','glow'})
    p.style_layer.setCurrentIndex(p.style_layer.findData('translation'));yield .15
    original=state('original')
    dialog_edit('outline','style_outline_color',1);yield .1
    a.check('translation gradient leaves original intact',state('original')==original)
    p.style_layer.setCurrentIndex(p.style_layer.findData('original'));yield .1
    # Real store and normal preset application keep the entire paint map.
    recipe=effective_layer_recipe(p.project,p.project.cues[0],'original').to_dict()
    style=copy.deepcopy(next(s for s in p.project.styles if s.id==p.project.cues[0].style_id))
    style.id='user-effect-paints-acceptance';style.name='完整渐变验收'
    presets=StylePresetStore();presets.upsert(style,recipe)
    p._refresh_style_presets(style.id)
    index=p.style_preset.findData(style.id)
    a.check('saved preset visible',index>=0)
    p.style_preset.setCurrentIndex(index);p.style_preset.activated.emit(index);yield .25
    a.check('applied preset retains all five effect paints',set(state('original')['paints'])=={'outline','outline2','background','shadow','glow'})
    p.style_controller._commit_style_now();p.style_controller.flush_pending_application()
    save_project(p.project,out/'colors-saved.2byteproj')
    a.result['colors']={layer:state(layer) for layer in ('original','translation')}
    p.undo_stack.setClean()
    yield from a.seek(500,'final gradient preview')
    _capture(window,out/'all-gradients-workbench.png')
    from ..projects.project_range import set_range
    set_range(p.project,0,4000,undo_stack=p.undo_stack)
    p._open_render_dialog(skip_preflight=True);yield .4
    ui=p.export_workspace
    a.check('normal video export workspace',ui is not None)
    ui.directory.setText(str(out));ui.filename_prefix.setText('');ui.filename_suffix.setText('');ui.filename.setText('all-effect-gradients')
    ui.audio.setCurrentIndex(ui.audio.findData('none'))
    index=ui.encoder.findData('libx264')
    if index>=0:ui.encoder.setCurrentIndex(index)
    destination=ui.export_target().full_path
    ui.export_button.click()
    yield a.wait(lambda:not ui._running,'actual gradient video export',180)
    a.check('produced gradient video',destination.is_file() and destination.stat().st_size>1000)
    a.result['video']=str(destination)
    p._close_export_workspace();p.undo_stack.setClean()



def eyedrop_suite(a,window,out):
    import ctypes
    from PySide6.QtCore import QPoint,QTimer,Qt
    from PySide6.QtGui import QColor,QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QScrollArea
    from ..caption_style.caption_layer_transform import displayed_layer
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..timeline.selection_scope import SelectionScope
    from .blank_project_audit import _capture
    p=a.page
    user=ctypes.windll.user32
    user.GetForegroundWindow.restype=ctypes.c_void_p
    user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
    foreground=user.GetForegroundWindow()
    kernel=ctypes.windll.kernel32
    current_thread=kernel.GetCurrentThreadId()
    foreground_thread=user.GetWindowThreadProcessId(foreground,None) if foreground else 0
    attached=bool(foreground_thread and foreground_thread!=current_thread and user.AttachThreadInput(current_thread,foreground_thread,True))
    try:
        user.ShowWindow(int(window.winId()),9)
        window.raise_();window.activateWindow()
        user.BringWindowToTop(int(window.winId()))
        activated=bool(user.SetForegroundWindow(int(window.winId())))
    finally:
        if attached:user.AttachThreadInput(current_thread,foreground_thread,False)
    a.result['foreground_attempt']=dict(previous=int(foreground or 0),owned=int(window.winId()),attached=attached,activated=activated)
    yield a.wait(lambda:user.GetForegroundWindow()==int(window.winId()),'owned foreground for actual eyedropper',25)
    p.select_cue(p.project.cues[0].id)
    p.cue_controller.apply_selection_scope(SelectionScope.explicit([p.project.cues[0].id],p.project.cues[0].id))
    p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
    p.style_layer.setCurrentIndex(p.style_layer.findData('original'))
    p.context_drawer.setCurrentIndex(1);p._set_major_panel_visible('context',True)
    yield from a.seek(500,'eyedrop actual media')
    yield .3
    a.check('screen sampler owns foreground',user.GetForegroundWindow()==int(window.winId()))
    point=p.video.mapToGlobal(QPoint(p.video.width()//2,max(36,p.video.height()//5)))
    screen=QGuiApplication.screenAt(point)
    image=screen.grabWindow(0).toImage();local=point-screen.geometry().topLeft();ratio=image.devicePixelRatio()
    expected=image.pixelColor(int(local.x()*ratio),int(local.y()*ratio))
    a.check('actual displayed fixture pixel',expected.blue()>expected.red() and expected.blue()>40 and expected.blue()<130)
    a.result['actual_screen_sampling']=dict(expected=expected.name(),point=[point.x(),point.y()],dpr=ratio,entries=[])
    def state():
        cue=p.project.cues[0];shown=displayed_layer(p.project,cue,'original') or cue
        return build_visual_cue_snapshot(p.project,shown.id,resolved_cue=shown).pixel_hash()
    for target,attribute in (('fill','style_fill_color'),('outline','style_outline_color'),('outline2','style_outline2_color'),('background','style_back_color'),('shadow','style_shadow_color'),('glow','style_glow_color')):
        for cancel in (False,True):
            saved=state();before=p.undo_stack.index();result={};a.timer.stop()
            def drive(target=target,cancel=cancel):
                dialog=QApplication.activeModalWidget()
                if dialog is None:QTimer.singleShot(40,drive);return
                try:
                    QTest.mouseClick(dialog.mode_segment.button(1),Qt.LeftButton)
                    dialog._select_gradient_stop(0)
                    dialog.picker.alpha_spin.setValue(40)
                    QTest.mouseClick(dialog.picker.eyedropper,Qt.LeftButton)
                    def sample():
                        try:
                            overlay=dialog.picker._dropper
                            if overlay is None:raise RuntimeError('No actual eyedrop overlay')
                            a.check(target+' sampling remains owned',int(user.GetForegroundWindow() or 0) in {int(window.winId()),int(dialog.winId()),int(overlay.winId())})
                            QTest.mouseClick(overlay,Qt.RightButton if cancel else Qt.LeftButton,pos=overlay.mapFromGlobal(point))
                            if not cancel:
                                color=dialog.picker.color();stop=QColor(dialog.gradient._selected.color)
                                a.result['actual_screen_sampling'].setdefault('samples',[]).append(dict(target=target,color=color.name(QColor.HexArgb),stop=stop.name(QColor.HexArgb),expected=expected.name()))
                                a.check(target+' eyedrop value and stop update',color.rgb()==expected.rgb() and stop.rgb()==expected.rgb() and stop.alpha()==102)
                                a.check(target+' eyedrop numeric value update',dialog.picker.hex_edit.text().lower()==expected.name().lower())
                            result['color']=dialog.picker.color().name(QColor.HexArgb)
                            dialog.reject() if cancel else dialog.accept()
                        except Exception:result['error']=traceback.format_exc();dialog.reject()
                    QTimer.singleShot(220,sample)
                except Exception:result['error']=traceback.format_exc();dialog.reject()
            QTimer.singleShot(120,drive)
            try:
                button=p.style_fill_button if target=='fill' else p.style_back_button if target=='background' else getattr(p,'style_'+target+'_swatch').findChild(p._style_color_button_type())
                scroll=button.parentWidget()
                while scroll is not None and not isinstance(scroll,QScrollArea):scroll=scroll.parentWidget()
                if scroll is not None:scroll.ensureWidgetVisible(button)
                QTest.mouseClick(button,Qt.LeftButton)
            finally:a.timer.start()
            if result.get('error'):raise RuntimeError(result['error'])
            a.check(target+' actual eyedrop history '+str(cancel),p.undo_stack.index()==before+(0 if cancel else 1))
            if cancel:a.check(target+' actual eyedrop cancel restores paint',state()==saved)
            a.result['actual_screen_sampling']['entries'].append(dict(target=target,cancel=cancel,**result))
            yield .12
    _capture(window,out/'actual-eyedrop-workbench.png')
    p.undo_stack.setClean()
