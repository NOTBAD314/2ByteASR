"""Opt-in timeline checks through the normal MainWindow project session."""
from pathlib import Path
import copy


def run(window, page, output, check):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from ..design.theme_manager import request_theme, theme_key
    from ..projects.studio_project import save_project, load_project
    from ..caption_style.motion_timeline_ui import MotionTimeline
    from ..studio.studio_ai_menu import build_ai_menu
    app=QApplication.instance()
    page.select_cue('a');page.video.set_paused(True)
    page.context_drawer.setCurrentIndex(page.motion_tab_index)
    page.motion_scope.setCurrentIndex(page.motion_scope.findData('current'))
    inspector=page.motion_inspector;timeline=inspector.tabs
    for theme in ('sand','midnight'):
        request_theme(theme);QTest.qWait(350)
        check(theme+' timeline actual window',theme_key()==theme and isinstance(timeline,MotionTimeline) and timeline.isVisible())
        inspector.choose('entry','zoom_in');inspector.choose('exit','push_out')
        inspector.tabs.setCurrentIndex(0);QTest.qWait(200)
        e,l,x=(timeline.segment(s).geometry() for s in ('entry','loop','exit'))
        check(theme+' stages follow playback order',e.right()<l.left() and l.right()<x.left() and timeline.segment('words').y()>e.bottom())
        check(theme+' three effect columns',inspector.columns==3)
        check(theme+' scope footer visible',page.motion_scope.isVisible() and page.motion_language.isVisible())
        check(theme+' timeline and parameter scroller do not overlap',timeline.geometry().bottom()<inspector.cards_scroll.geometry().top())
        check(theme+' word lane stays inside visible timeline',timeline.rect().contains(timeline.segment('words').geometry()))
        import json
        metrics={name:dict(rect=w.geometry().getRect(),min=w.minimumHeight(),max=w.maximumHeight(),hint=(w.sizeHint().width(),w.sizeHint().height())) for name,w in [('panel',page.motion_panel),('inspector',inspector),('timeline',timeline),('words',timeline.segment('words')),('params',inspector.params_card),('scroll',inspector.cards_scroll),('viewport',inspector.cards_scroll.viewport())]}
        (Path(output)/('motion-geometry-'+theme+'.json')).write_text(json.dumps(metrics,indent=2),'utf8')
        before=page.effect_duration.value();depth=page.undo_stack.count();old=copy.deepcopy(page.project.effects[page.project.cues[0].effect_id])
        grip=timeline.grips['entry'];at=grip.rect().center()
        QTest.mousePress(grip,Qt.LeftButton,pos=at)
        for dx in (10,25,40):QTest.mouseMove(grip,at+QPoint(dx,0));QTest.qWait(20)
        QTest.mouseRelease(grip,Qt.LeftButton,pos=at+QPoint(40,0));QTest.qWait(100)
        value=page.effect_duration.value()
        check(theme+' actual handle changes duration',value>before and timeline.durations['entry']==value)
        check(theme+' one gesture one command',page.undo_stack.count()==depth+1)
        page.undo_stack.undo();QTest.qWait(80)
        check(theme+' one undo restores exact effect',page.project.effects[page.project.cues[0].effect_id]==old)
        page.undo_stack.redo();QTest.qWait(80)
        check(theme+' redo restores duration',page.project.effects[page.project.cues[0].effect_id]['entry']['duration']==value)
        timeline.set_time(100,3000,(400,400));first=timeline.playhead.x
        timeline.set_time(1500,3000,(400,400));middle=timeline.playhead.x
        timeline.set_time(2900,3000,(400,400));last=timeline.playhead.x
        check(theme+' playhead traverses all phases',first<middle<last)
        window.grab().save(str(Path(output)/('motion-timeline-'+theme+'.png')))
        tile=inspector.cards['entry','zoom_in']
        inspector.cards_scroll.ensureWidgetVisible(tile,0,0);QTest.qWait(120)
        at=tile.mapTo(inspector.cards_scroll.viewport(),QPoint())
        (Path(output)/('tile-geometry-'+theme+'.json')).write_text(json.dumps(dict(top=at.y(),height=tile.height(),viewport=inspector.cards_scroll.viewport().height(),scroll=inspector.cards_scroll.verticalScrollBar().value(),maximum=inspector.cards_scroll.verticalScrollBar().maximum())), 'utf8')
        check(theme+' effect tile reachable without clipping',at.y()>=0 and at.y()+tile.height()<=inspector.cards_scroll.viewport().height())
        check(theme+' effect tile visible through all ancestors',tile.visibleRegion().boundingRect().contains(tile.rect()))
        window.grab().save(str(Path(output)/('motion-cards-'+theme+'.png')))
        inspector.cards_scroll.verticalScrollBar().setValue(0)
    saved=save_project(page.project,Path(output)/'motion-saved.2byteproj');loaded=load_project(saved)
    check('timeline survives save reload',loaded.effects[loaded.cues[0].effect_id]==page.project.effects[page.project.cues[0].effect_id])
    menu=QMenu(page);build_ai_menu(page,menu);menu.aboutToShow.emit()
    check('AI menu offers range and explains missing points',page.ai_range_reasr_action in menu.actions() and not page.ai_range_reasr_action.isEnabled() and bool(page.ai_range_reasr_action.toolTip()))
    from ..app.bunny_manual import MANUAL
    from ..app.bunny_persona import system_prompt
    from ..app.bunny_lore import feature_index
    prompt=system_prompt(feature_index())
    check('manual matches current editor bindings','Shift+F' in MANUAL and 'Shift+E' in MANUAL and '换代词已经不用了' in MANUAL)
    check('manual always includes blank range instructions','只重新识别这一段字幕' in prompt and '设置入点' in prompt and '设置出点' in prompt)
    from ..projects.studio_project import save_autosave, autosave_path, PROJECT_SUFFIX
    from ..projects.project_dirty_guard import ProjectDirtyGuard
    from ..projects.save_changes_dialog import SaveChangesDialog
    from PySide6.QtCore import QTimer
    import hashlib
    official=Path(page.project_path);official_sha=hashlib.sha256(official.read_bytes()).hexdigest()
    candidate=save_autosave(page.project,official)
    canonical=autosave_path(page.project,official)
    def discard_choice():
        box=next((w for w in app.topLevelWidgets() if isinstance(w,SaveChangesDialog) and w.isVisible()),None)
        if box is None:QTimer.singleShot(20,discard_choice);return
        QTest.mouseClick(box.discard_button,Qt.LeftButton)
    QTimer.singleShot(20,discard_choice)
    accepted=ProjectDirtyGuard(page).confirm('退出应用')
    check('actual dont save removes own recovery points',accepted and not candidate.exists() and not canonical.exists()
          and not list(canonical.parent.glob(f'{canonical.stem}.*{PROJECT_SUFFIX}')))
    check('dont save preserves official project bytes',hashlib.sha256(official.read_bytes()).hexdigest()==official_sha)
    # Existing editor/background audit continues from the untouched original fixture.
    page.undo_stack.setClean();page.context_drawer.setCurrentIndex(1)
    request_theme('sand');QTest.qWait(200)
