"""End-to-end linked geometry, independent edits, persistence and burned pixels."""
import copy
import json
import os
from pathlib import Path
import threading
import time


def run(window,output):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project,hydrate_media_contract
    from ..studio.studio_helpers import probe_media_identity
    from ..caption_style.caption_layer_transform import resolved_values
    from ..caption_style.caption_group_transform import KEY
    from ..timeline.studio_commands import add_cue_command,split_cue_command,merge_cues_command
    from ..exports.export_timeline import write_export_ass
    from ..exports.video_export import capture_video_graph
    from ..exports.studio_render import RenderSettings,RenderJob,run_render_job
    from ..system.platform_media import ffmpeg_tool
    from .blank_project_audit import _capture
    from .studio_splitter_audit import _native_rects
    from scripts.capture_process_window import print_window
    result={'checks':[]}
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
    def wait(fn,label,seconds=45):
        end=time.monotonic()+seconds
        while not fn():
            if time.monotonic()>end:raise TimeoutError(label)
            QTest.qWait(10)
    media=Path(os.environ['TWOBYTEASR_PERF_MEDIA'])
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=12000,width=1280,height=720),
        cues=[StudioCue(f'cue-{i}',i*2000,(i+1)*2000,'字幕聯動測試'+str(i)) for i in range(5)],
        generation_metadata={'translations':{f'cue-{i}':'Linked caption '+str(i) for i in range(5)}},
        studio_state={'bilingual':{'mode':'bilingual'}})
    p.render_settings.update(play_res_x=1280,play_res_y=720,_cue_domain='timeline')
    p.styles[0].position_x=500;p.styles[0].position_y=480
    p.cues[-1].transform={'language_layers':{'original':{'position_x':200,'position_y':300}}}
    hydrate_media_contract(p,probe_media_identity(str(media)));p.validate()
    path=save_project(p,output/'字幕聯動 工程.2byteproj')
    page=window.studio_page;prior=page.project;page.undo_stack.setClean()
    window.showNormal();window.resize(1600,950);window.show()
    window.open_studio_project(str(path),mode='edit',source='workbench-geometry')
    wait(lambda:page.project is not prior and page._readiness.ready,'project readiness')
    QTest.qWait(600);page.video.set_paused(True);page._seek(.3);page.select_cue('cue-0')
    page.context_drawer.setCurrentIndex(1);panel=page.caption_transform_panel
    QTest.qWait(400)
    def current(cue_id='cue-0',language='original'):
        return resolved_values(page.project,page._cue_lookup[cue_id],language)
    def pixels_ready():
        scene=getattr(page,'_caption_scene',None)
        return scene is not None and scene.token and scene.token[2]==page._revision_store.render.visual_revision and scene.published is not None
    def enter(key,value):
        control=panel.controls[key];control.setFocus();control.selectAll()
        QTest.keyClicks(control,str(value));QTest.keyClick(control,Qt.Key_Return)
        wait(pixels_ready,'current revision pixels')
    panel.global_link.click();QTest.qWait(250)
    original=current();later=current('cue-4');translated=current('cue-4','translation')
    count=page.undo_stack.index();enter('position_x',55)
    dx=current()['position_x']-original['position_x']
    check('global numeric moves old individual override',abs(current('cue-4')['position_x']-later['position_x']-dx)<.01)
    check('global numeric also moves translation',abs(current('cue-4','translation')['position_x']-translated['position_x']-dx)<.01)
    gap=current()['position_y']-current(language='translation')['position_y']
    enter('scale_x',125)
    check('global scale and linked axes',abs(current('cue-4')['scale_x']-125)<.01 and abs(current('cue-4')['scale_y']-125)<.01)
    check('bilingual group spacing scales',abs((current()['position_y']-current(language='translation')['position_y'])-gap*1.25)<.1)
    page._seek(8.3);page.select_cue('cue-4');wait(pixels_ready,'later subtitle pixels')
    check('later subtitle shows same saved transform',panel.controls['scale_x'].value()==125)
    _capture(window,output/'later-linked-caption.png')
    page._seek(.3);page.select_cue('cue-0');QTest.qWait(350)
    panel.global_link.click()
    other=current('cue-4');other_translation=current(language='translation')
    enter('position_x',35)
    check('unlinked edit only selection',current('cue-4')==other and current(language='translation')==other_translation)
    before_apply=current('cue-4');index=page.undo_stack.index()
    panel.apply_all.click();wait(pixels_ready,'apply all pixels')
    fields=('position_x','position_y','scale_x','scale_y')
    check('apply all immediately replaces overrides',all(abs(current()[key]-current('cue-4')[key])<.01 for key in fields))
    check('apply all keeps bilingual separation',current(language='translation')['position_y']!=current()['position_y'])
    check('apply all one undo',page.undo_stack.index()==index+1)
    page.undo_stack.undo();check('batch undo restores old override',current('cue-4')==before_apply)
    page.undo_stack.redo();wait(pixels_ready,'redo pixels')
    page.position_edit_button.setChecked(True);panel.refresh();QTest.qWait(100)
    overlay=page.position_overlay
    point=overlay._measured_bounds.center().toPoint()
    stale_target=current('cue-4');index=page.undo_stack.index()
    QTest.mousePress(overlay,Qt.LeftButton,pos=point)
    QTest.mouseMove(overlay,point+QPoint(25,12),delay=0)
    page.select_cue('cue-4')
    QTest.mouseRelease(overlay,Qt.LeftButton,pos=point+QPoint(25,12))
    check('selection change rejects stale drag release',current('cue-4')==stale_target and page.undo_stack.index()==index)
    page.select_cue('cue-0');page._seek(.3)
    p=page.project
    baseline=[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id,copy.deepcopy(c.evidence_refs)) for c in p.cues]
    page.undo_stack.push(add_cue_command(p,StudioCue('new',10000,11000,'新增字幕'),changed=page._changed))
    check('new inserted cue inherits common geometry',all(abs(current('new')[key]-current('cue-0')[key])<.01 for key in fields))
    page.undo_stack.push(split_cue_command(p,'cue-0',1000,'字幕聯動','測試0',changed=page._changed))
    split=[c.id for c in p.cues if c.start_ms<2000]
    check('split retains transform',len(split)==2 and all(abs(current(c)[key]-current('cue-4')[key])<.01 for c in split for key in fields))
    page.undo_stack.push(merge_cues_command(p,split,changed=page._changed))
    check('merge retains transform',all(abs(current()[key]-current('cue-4')[key])<.01 for key in fields))
    check('text timing evidence preserved for untouched cues',
          [(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id,c.evidence_refs) for c in p.cues if c.id.startswith('cue-') and c.id!='cue-0']==baseline[1:])
    saved=save_project(p,output/'儲存重開.2byteproj');read=load_project(saved)
    check('saved shared geometry identical',read.studio_state[KEY]==p.studio_state[KEY])
    page.undo_stack.setClean();prior=p
    window.open_studio_project(str(saved),mode='edit',source='geometry reopen')
    wait(lambda:page.project is not prior and page._readiness.ready,'reopen')
    page.video.set_paused(True);page._seek(.3);page.select_cue('cue-0')
    QTest.qWait(500);wait(pixels_ready,'reopened pixels')
    check('reopen effective transforms',all(abs(current()[key]-resolved_values(read,read.cues[0],'original')[key])<.01 for key in fields))
    _capture(window,output/'reopened-transform.png')
    _,native=_native_rects(page.video)
    print_window(_native_rects.mpv_hwnd,(0,0,native[2],native[3])).save(output/'preview-native.png')
    ass=output/'linked.ass';write_export_ass(page.project,ass,fps=30)
    job=RenderJob(str(media),str(ass),str(output/'字幕位置 成片.mp4'),
        RenderSettings(encoder='libx264',width=1280,height=720,fps=30,quality=20,audio_codec='aac'),
        start_seconds=0,duration_seconds=2,video_graph=capture_video_graph(page.project))
    status={}
    def export():
        try:status['path']=run_render_job(ffmpeg_tool(),job)
        except Exception as exc:status['error']=repr(exc)
    worker=threading.Thread(target=export);worker.start()
    wait(lambda:not worker.is_alive(),'geometry export',90)
    check('actual burned video',bool(status.get('path')),status)
    result['output']=str(status.get('path'));result['completed']=True
    result['passed']=all(c['passed'] for c in result['checks']);save()
