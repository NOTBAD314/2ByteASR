"""Normal MainWindow, paused mutations and long-project source audit."""
from copy import deepcopy
import json
import os
from pathlib import Path
import time


def run(output, window=None):
    from ..test_isolation import install_pytest_network_guard
    install_pytest_network_guard()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from ..app.ui import MainWindow, _register_bundled_fonts, _app_font
    from ..design.theme_manager import apply_theme
    from ..projects.studio_project import load_project, save_project, StudioCue, StudioMedia, SubtitleProject
    from ..timeline.studio_commands import delete_cues_command, add_cue_command, SetCueFieldsCommand
    from ..studio.studio_ai_flow import StudioAIFlowMixin
    from ..providers.endpoint_editor_ui import EndpointEditor
    from ..system.processes import run_hidden_subprocess
    import subtitle_core as legacy
    from ..runtime_paths import detect_install_root
    root=detect_install_root()
    EndpointEditor._queue_model_discovery=lambda *a,**k:None
    StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**k:None
    app=QApplication.instance() or QApplication([])
    _register_bundled_fonts();app.setFont(_app_font());apply_theme('grape',app)
    checks=[];timings=[];traces=[]
    def check(name, passed, detail=None):
        checks.append(dict(name=name,passed=bool(passed),detail=detail))
        (output/'progress.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),'utf8')
        if not passed:raise AssertionError(name+': '+str(detail))
    def settle(seconds=.05):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents();time.sleep(.004)
    def wait(predicate, seconds=25):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:settle(.02)
        if not predicate():raise TimeoutError(str(predicate))
    media=output/'fixture.mp4'
    run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-f','lavfi','-i',
        'color=c=0x334155:s=960x540:r=30:d=7','-c:v','libx264','-preset','ultrafast',str(media)],
        capture_output=True,check=True,timeout=30,purpose='collision headed synthetic media')
    # Reopen a real old automatic allocation rather than only new clean cues.
    old=load_project(Path(os.environ.get('TWOBYTEASR_COLLISION_LEGACY_FIXTURE') or root/'tmp/subtitle-collision-20261110/pixels-before/fixture.2byteproj'))
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=7000,width=960,height=540),
        cues=deepcopy(old.cues), styles=deepcopy(old.styles),speakers=deepcopy(old.speakers))
    fixture=output/'fixture.2byteproj';save_project(p,fixture)
    win=window or MainWindow([],legacy,object(),None);win.resize(1440,920);win.show()
    try:
        win.open_studio_project(str(fixture))
        wait(lambda:win.built_page('studio') is not None and win.built_page('studio').project is not None)
        page=win.studio_page
        wait(lambda:win.__dict__.get('_studio_loading_session') is None or (not win._studio_loading_session.active and not win._studio_loading_session.view.isVisible()))
        settle(1.)
        def seek(at):
            page.video.set_paused(True);page._seek(at/1000.);settle(.12)
        def scene(ids, label):
            def ready():
                value=getattr(page,'_caption_scene',None)
                if value is None:return False
                trace=value.trace()
                return set(trace['rendered_cue_ids'])==set(ids) and trace['visible'] and value.still_current(value.token)
            try:wait(ready)
            except Exception:
                value=getattr(page,'_caption_scene',None)
                diagnostic=dict(label=label,project_cues=[c.id for c in page.project.cues],
                    sample_ms=page._caption_sample_ms(),runtime_cues=[c.id for c in page.session.runtime.cues_at(1000)],
                    token=value.token if value else None,trace=value.trace() if value else None,
                    metrics=value.metrics[-3:] if value else None,failures=str(value.failures) if value else None,
                    mapping=page._revision_store.render.mapping_revision,visual=page._revision_store.render.visual_revision)
                (output/'scene-timeout.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2,default=str),'utf8')
                raise
            value=page._caption_scene
            trace=value.trace();traces.append(dict(label=label,trace=deepcopy(trace)))
            win.grab().save(str(output/f'{label}-window.png'))
            value.published.image.save(str(output/f'{label}-scene.png'))
            # mpv is the actual video plane, independently of the Qt snapshot.
            shot=output/f'{label}-mpv.png'
            page.video.controller.screenshot_to_file(shot)
            wait(lambda:shot.is_file(),3)
            check(label+' actual mpv pixels',not QImage(str(shot)).isNull())
            return {r['cue_id']:r for r in trace['cue_pixels']}
        seek(1000)
        both=scene(['lower','upper'],'01-two')
        base=both['upper']['base_position'][1]
        check('old saved automatic anchor recovered',base==1015)
        check('two cues avoid',both['upper']['collision_offset_y']>0)
        original=deepcopy([(c.id,c.text,c.start_ms,c.end_ms,c.transform) for c in page.project.cues])
        began=time.perf_counter()
        page.undo_stack.push(delete_cues_command(page.project,['lower'],page._changed))
        one=scene(['upper'],'02-paused-delete-lower')
        timings.append(dict(action='paused delete to published scene',ms=(time.perf_counter()-began)*1000))
        check('paused deletion returns upper to exact base',one['upper']['position'][1]==base)
        page.undo_stack.undo()
        restored=scene(['lower','upper'],'03-undo')
        check('undo layout same',restored['upper']['position']==both['upper']['position'])
        page.undo_stack.redo();scene(['upper'],'04-redo')
        page.undo_stack.undo();scene(['lower','upper'],'05-restored')
        page.undo_stack.push(delete_cues_command(page.project,['upper'],page._changed))
        lower=scene(['lower'],'06-paused-delete-upper')
        check('lower stays at own base',lower['lower']['collision_offset_y']==0)
        page.undo_stack.undo();scene(['lower','upper'],'07-restored')
        page._subtitle_visibility_changed('S0',False)
        hidden=scene(['upper'],'08-paused-hide')
        check('eye hides subtitle and resets peer',hidden['upper']['collision_offset_y']==0)
        page._subtitle_visibility_changed('S0',True);scene(['lower','upper'],'09-eye-show')
        page.undo_stack.push(SetCueFieldsCommand(page.project,'lower',{'end_ms':900},'改时',page._changed))
        changed=scene(['upper'],'10-paused-time')
        check('paused timing resets peer',changed['upper']['collision_offset_y']==0)
        page.undo_stack.undo();scene(['lower','upper'],'11-time-undo')
        upper=next(c for c in page.project.cues if c.id=='upper')
        transform=deepcopy(upper.transform);transform.update(position_x=960,position_y=960)
        page.undo_stack.push(SetCueFieldsCommand(page.project,'upper',{'transform':transform},'手动位置',page._changed))
        scene(['lower','upper'],'12-manual-collision')
        page.undo_stack.push(delete_cues_command(page.project,['lower'],page._changed))
        manual=scene(['upper'],'13-manual-recovery')
        check('manual base preserved',manual['upper']['position'][1]==960)
        page.undo_stack.undo();page.undo_stack.undo();scene(['lower','upper'],'14-restored')
        third=StudioCue('third',200,4500,'第三条字幕',speaker_id='S0')
        page.undo_stack.push(add_cue_command(page.project,third,page._changed))
        triple=scene(['lower','upper','third'],'15-three')
        check('third avoids other two',triple['third']['position'][1]<triple['upper']['position'][1])
        for key in ['lower','upper','third']:
            page.undo_stack.push(delete_cues_command(page.project,[key],page._changed))
            scene([c.id for c in page.project.cues],f'16-three-delete-{key}')
            page.undo_stack.undo();scene(['lower','upper','third'],f'17-three-undo-{key}')
        page.undo_stack.undo();scene(['lower','upper'],'18-two')
        seek(4500)
        ended=scene(['upper'],'19-peer-ended')
        check('playhead beyond peer end resets',ended['upper']['position'][1]==base)
        seek(1000);jumped=scene(['lower','upper'],'20-jump-back')
        check('jump deterministic',jumped['upper']['position']==both['upper']['position'])
        page.video.set_paused(False);settle(.3);page.video.set_paused(True)
        played=scene(['lower','upper'],'21-play-pause')
        check('continuous playback same layout',played['upper']['position']==both['upper']['position'])
        upper=next(c for c in page.project.cues if c.id=='upper')
        appearance={**upper.appearance_override,'font_size':110,'shadow':8,'border_style':3}
        page.undo_stack.push(SetCueFieldsCommand(page.project,'upper',
            {'text':'修改第一行\n修改第二行','appearance_override':appearance},'多行阴影背景',page._changed))
        styled=scene(['lower','upper'],'21b-paused-multiline-shadow-background')
        check('paused content and style update retained avoidance',styled['upper']['collision_offset_y']>0)
        page.undo_stack.undo();restyled=scene(['lower','upper'],'21c-style-undo')
        check('style undo restores original layout',restyled['upper']['position']==both['upper']['position'])
        win.resize(1200,800);settle(.12)
        resized=scene(['lower','upper'],'21d-resize')
        check('window resize preserves video layout',resized['upper']['position']==both['upper']['position'])
        win.resize(1440,920);settle(.12)
        page.undo_stack.push(SetCueFieldsCommand(page.project,'upper',
            {'transform':{'position_x':280,'position_y':500},'text':'左侧'},'左右分离',page._changed))
        separated=scene(['lower','upper'],'21e-separated')
        check('separated captions do not move',all(row['collision_offset_y']==0 for row in separated.values()))
        page.undo_stack.undo();scene(['lower','upper'],'21f-separated-undo')
        check('no persistent displacement drift',original==[(c.id,c.text,c.start_ms,c.end_ms,c.transform) for c in page.project.cues])
        saved=output/'reopened.2byteproj';save_project(page.project,saved)
        check('save retains user transforms',[(c.id,c.transform) for c in load_project(saved).cues]==[(c.id,c.transform) for c in page.project.cues])
        # 6000 cues: verify that the renderer only receives the current two.
        p=load_project(saved)
        p.cues.extend(StudioCue(f'long-{i}',10000+i*3000,12000+i*3000,f'长工程字幕 {i}',speaker_id='S0') for i in range(6000))
        p.media.duration_ms=18020000
        longpath=output/'long.2byteproj';save_project(p,longpath)
        page.undo_stack.setClean();win.open_studio_project(str(longpath))
        wait(lambda:win.built_page('studio') is not None and win.built_page('studio').project is not None and len(win.built_page('studio').project.cues)==6002,40)
        page=win.studio_page;settle(.6);seek(1000);scene(['lower','upper'],'22-long-two')
        import twobyteasr.caption_style.collision_layout as layout_module
        from unittest.mock import patch
        sizes=[];original_solve=layout_module.solve_layout
        def counted(ss,**kwargs):
            ss=tuple(ss);sizes.append(len(ss));return original_solve(ss,**kwargs)
        with patch.object(layout_module,'solve_layout',counted):
            began=time.perf_counter()
            page.undo_stack.push(delete_cues_command(page.project,['lower'],page._changed))
            immediate=(time.perf_counter()-began)*1000
            scene(['upper'],'23-long-delete')
            timings.append(dict(action='6002 cues delete command',ms=immediate))
            timings.append(dict(action='6002 cues delete to published',ms=(time.perf_counter()-began)*1000))
            check('long edit uses active set or cached scene',max(sizes,default=0)<=2,dict(measured_sizes=sizes,cache_reused=not sizes))
        check('stale asynchronous token rejected',not page._caption_scene.still_current((0,0,0,0,(),'',0,0,0,0)))
        page.undo_stack.setClean()
    except Exception:
        import traceback
        (output/'error.txt').write_text(traceback.format_exc(),'utf8');win.grab().save(str(output/'failure.png'))
        raise
    finally:
        (output/'result.json').write_text(json.dumps(dict(checks=checks,timings=timings,traces=traces),ensure_ascii=False,indent=2),'utf8')
        if win.studio_page.project:win.studio_page.undo_stack.setClean()
        win.close();settle(2.)
    if window is not None:
        return 0
    # Same deliberate post-cleanup Windows shutdown as the normal app entry.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.TerminateProcess(kernel.GetCurrentProcess(),0)
    os._exit(0)
