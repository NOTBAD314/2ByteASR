import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_studio_style_controller import _page,_finish
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


@pytest.mark.parametrize('graph',[False,True])
def test_keyboard_refresh_commit_shadow_and_undo(tmp_path,monkeypatch,graph):
    app,page=_page(tmp_path,monkeypatch)
    try:
        if graph:
            from twobyteasr.caption_design.visual_design_graph import VisualDesignGraph
            recipe=page._base_recipe_for_style(page.project.styles[0]).to_dict()
            recipe['engine']='remotion'
            recipe['visualGraph']=VisualDesignGraph(name='Polar shadow input fixture').to_dict()
            page.project.style_recipes[page.project.cues[0].style_id]=recipe
            page._load_style_inspector()
        page.show();app.processEvents()
        for name,text,key,expected in [('style_shadow_distance','17','offset_x',12.02),
                                        ('style_shadow_blur','13','blur_radius',13.),
                                        ('style_shadow_opacity','71','opacity',.71),
                                        ('style_shadow_angle_value','90','offset_x',0.)]:
            control=getattr(page,name)
            before=build_visual_cue_snapshot(page.project,'a').shadow
            count=page.undo_stack.count()
            control.setFocus();control.lineEdit().selectAll();QTest.keyClicks(control.lineEdit(),text)
            page._load_style_inspector()
            assert control.value()==float(text)
            QTest.keyClick(control.lineEdit(),Qt.Key.Key_Return)
            QTest.qWait(220)
            assert control.value()==float(text)
            after=build_visual_cue_snapshot(page.project,'a').shadow
            assert after[key]==pytest.approx(expected,abs=.02)
            assert page.undo_stack.count()==count+1
            page.undo_stack.undo();assert build_visual_cue_snapshot(page.project,'a').shadow==before
            page.undo_stack.redo();assert build_visual_cue_snapshot(page.project,'a').shadow==after
            control.clearFocus();app.processEvents()
            page._load_style_inspector();assert control.value()==float(text)
        control=page.style_shadow_blur
        control.setFocus();control.lineEdit().selectAll();QTest.keyClicks(control.lineEdit(),'19')
        page.ai_prompt.setFocus();QTest.qWait(220)
        assert build_visual_cue_snapshot(page.project,'a').shadow['blur_radius']==19
        control.stepUp();QTest.qWait(220)
        assert build_visual_cue_snapshot(page.project,'a').shadow['blur_radius']==20
        from twobyteasr.projects.studio_project import save_project,load_project
        expected=build_visual_cue_snapshot(page.project,'a').shadow
        reopened=load_project(save_project(page.project,tmp_path/'shadow-reopen.2byteproj'))
        assert build_visual_cue_snapshot(reopened,'a').shadow==expected
    finally:_finish(page)
