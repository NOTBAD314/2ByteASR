"""Real dialogs and real bilingual burn-in, using generated media only."""
from pathlib import Path
import copy
import json


def run(output, *, speaker_names=False):
    import av
    import numpy as np
    from PySide6.QtWidgets import QApplication, QFileDialog
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker, SubtitleStyle, save_project, load_project
    from ..design.theme_manager import apply_application_theme
    from ..system.platform_media import ffmpeg_tool
    from ..system.processes import run_hidden_subprocess
    from ..exports.completion_export import CompletionExportDialog
    from ..exports.studio_export_ui import SubtitleExportDialog
    from ..exports.export_timeline import write_export_ass
    from ..exports.video_export import capture_video_graph
    from ..exports.studio_render import RenderJob, RenderSettings
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    from ..timeline.studio_media_pool import sync_primary_video_track_from_sequence
    from .blank_project_audit import _capture

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, "grape")
    ffmpeg = Path(ffmpeg_tool())
    source = output / "source.mp4"
    run_hidden_subprocess([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=0x17202a:s=960x540:r=24000/1001:d=6", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=6", "-c:v", "libx264",
        "-preset", "ultrafast", "-c:a", "aac", str(source)], purpose="bilingual audit fixture", check=True, timeout=20)
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=6000, width=960, height=540),
        speakers=[StudioSpeaker("S01", "甲"), StudioSpeaker("S02", "乙")],
        cues=[StudioCue("one", 1000, 5000, "Are you ready?", speaker_id="S01"),
              StudioCue("two", 1800, 5000, "Let's go!", speaker_id="S02", style_id="gradient")],
        styles=[SubtitleStyle("default", "普通字幕", font_size=80),
                SubtitleStyle("gradient", "渐变字幕", font_size=80)],
        generation_metadata={"language": {"code": "en"}, "translations": {"one": "你准备好了吗", "two": "我们出发吧"}},
        studio_state={"bilingual": {"mode": "bilingual", "order": "translation_first"}})
    project.style_recipes["gradient"] = {"name": "Gradient", "engine": "remotion", "motion": {"mode": "none"},
        "colors": {"fill": {"type": "linear-gradient", "angle": 0, "stops": [
            {"position": 0, "color": "#FFFFAA00"}, {"position": 1, "color": "#FFFFFF00"}]}}}
    project.cues[0].transform = {"position_x": 520, "position_y": 950}
    project.cues[1].transform = {"position_x": 1420, "position_y": 950}
    if speaker_names:
        project.speakers[0].name='小明'
        project.speakers[1].name='另一位名字很长的讲解员'
        project.studio_state['show_speaker_names']=True
    project.validate()
    sequence = EditSequence(source_path=str(source), source_duration_ms=6000,
        segments=[VideoSegment("cut", str(source), 1000, 6000, 0, 5000)])
    store_sequence(project, sequence)
    sync_primary_video_track_from_sequence(project, sequence)
    project.media_pool[0].video_metadata["fps"] = 24000/1001
    project_path = save_project(project, output / "dialogue.2byteproj")
    project = load_project(project_path)
    result = {"checks": [], "scope": "source; private Windows desktop; synthetic media; real dialogs and FFmpeg"}
    def check(name, condition, detail=None):
        result["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(name)

    # Completion-page export used to call the original-only export path.
    target = output / "completion"; target.mkdir()
    QFileDialog.getExistingDirectory = lambda *a, **kw: str(target)
    dialog = CompletionExportDialog(project, "dialogue")
    dialog.show(); QTest.qWait(300)
    _capture(dialog, output / "completion-before.png")
    dialog._export()
    QTest.qWait(150)
    check("completion SRT keeps both translations", all(t in (target/"dialogue.srt").read_text("utf8")
        for t in ["你准备好了吗", "我们出发吧", "Are you ready?", "Let's go!"]))
    dialog.close()

    studio = SubtitleExportDialog(project, project_path, export_on_accept=True)
    studio.show(); QTest.qWait(300)
    _capture(studio, output / "studio-export.png")
    check("studio offers all language layers", set(studio._selected_layers()) == {"original", "translation", "bilingual"})
    studio.close()

    def render(mode, *, animated=False, names=None, words=False):
        sample = copy.deepcopy(project)
        sample.studio_state["bilingual"]["mode"] = mode
        name = mode + ("-animated" if animated else "")
        if names is not None:
            sample.studio_state['show_speaker_names']=names
            name += '-names-on' if names else '-names-off'
        if words:
            name += '-words'
            sample.effects['measured']={'word_highlight':{'type':'word_reveal'}}
            for cue in sample.cues:
                cue.effect_id='measured';cue.evidence_refs=[cue.id]
                sample.asr_evidence[cue.id]={'words':[dict(text=word,start_ms=cue.start_ms+300+i*400,
                    end_ms=cue.start_ms+600+i*400) for i,word in enumerate(cue.text.split())]}
        if animated:
            sample.effects["fade"] = {"entry": {"type": "fade", "duration": 200},
                                      "exit": {"type": "fade", "duration": 200}}
            sample.cues[1].effect_id = "fade"
        ass = output / f"{name}.ass"
        frozen = write_export_ass(sample, ass, fps=24000/1001)
        preview_frames = []
        def receive_preview(image, milliseconds, phase):
            if phase == "已烧录字幕":
                preview_frames.append((milliseconds, image.copy()))
        job = RenderJob(str(source), str(ass), str(output/f"{name}.mp4"),
            RenderSettings(encoder="libx264", preset="ultrafast", width=960, height=540,
                           fps=24000/1001, quality=12, audio_codec="aac"),
            duration_seconds=5, video_graph=capture_video_graph(sample),
            preview_callback=receive_preview)
        AdvancedRendererBackend().render(frozen, ffmpeg, job)
        if not preview_frames:
            raise AssertionError(f"{name}: no actual burn-in progress preview received")
        at, preview = min(preview_frames, key=lambda item: abs(item[0]-2000))
        if abs(at-2000) > 510:
            raise AssertionError(f"{name}: progress preview did not reach the dialogue")
        preview.save(str(output/f"{name}-progress-preview.png"))
        rgb = preview.convertToFormat(QImage.Format.Format_RGB888)
        preview_pixels = np.frombuffer(rgb.constBits(), dtype=np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
        preview_pixels = preview_pixels[:, :rgb.width()*3].reshape(rgb.height(), rgb.width(), 3).copy()
        with av.open(job.output_path) as container:
            frame = next(f for f in container.decode(video=0) if float(f.pts*f.time_base) >= 2)
            pixels = frame.to_ndarray(format="rgb24").copy()
        image = QImage(pixels.data, 960, 540, pixels.strides[0], QImage.Format.Format_RGB888).copy()
        image.save(str(output/f"{name}-frame.png"))
        if words:
            with av.open(job.output_path) as container:
                early=next(f for f in container.decode(video=0) if float(f.pts*f.time_base)>=.9)
                early_pixels=early.to_ndarray(format='rgb24').copy()
            QImage(early_pixels.data,960,540,early_pixels.strides[0],QImage.Format.Format_RGB888).copy().save(str(output/f'{name}-early-frame.png'))
        return pixels, preview_pixels

    original, original_preview = render("original")
    bilingual, bilingual_preview = render("bilingual")
    animated, animated_preview = render("bilingual", animated=True)
    if speaker_names:
        unnamed,_ = render('original',names=False)
        for label,x1,x2 in [('native',0,480),('advanced',480,960)]:
            pixels=np.max(np.abs(original[:,x1:x2].astype(int)-unnamed[:,x1:x2].astype(int)),axis=2)
            check(label+' name changes actual video pixels',np.count_nonzero(pixels>40)>300,
                  int(np.count_nonzero(pixels>40)))
        from ..caption_style.bilingual_layout import project_display_cues
        view=project_display_cues(project)
        check('bilingual names once per cue',all(sum(c.text.count(s.name+'：') for c in view)==1 for s in project.speakers))
        check('source and user positions preserved',project.cues[0].text=='Are you ready?' and
              project.cues[0].transform=={'position_x':520,'position_y':950} and
              project.cues[1].transform=={'position_x':1420,'position_y':950})
        background=np.array([23,32,42])
        for label,pixels in [('original',original),('bilingual',bilingual),('animated',animated)]:
            edges=np.concatenate((pixels[:,:12],pixels[:,-12:]),axis=1)
            check(label+' names inside video edges',not np.any(np.max(np.abs(edges.astype(int)-background),axis=2)>40))
        render('original',words=True)
    # Both actors must add a visible translation above their lower original.
    for name, x1, x2 in [("native", 50, 480), ("advanced", 500, 950)]:
        diff = np.max(np.abs(bilingual[340:445, x1:x2].astype(int)-original[340:445, x1:x2].astype(int)), axis=2)
        check(name+" translation has actual burned-in pixels", np.count_nonzero(diff > 40) > 300,
              int(np.count_nonzero(diff > 40)))
        animated_diff = np.max(np.abs(animated[340:445, x1:x2].astype(int)-original[340:445, x1:x2].astype(int)), axis=2)
        check(name+" translation survives animated export", np.count_nonzero(animated_diff > 40) > 300,
              int(np.count_nonzero(animated_diff > 40)))
        for route, pixels in [("static", bilingual_preview), ("animated", animated_preview)]:
            region = np.s_[round(340*2/3):round(445*2/3), round(x1*2/3):round(x2*2/3)]
            preview_diff = np.max(np.abs(pixels[region].astype(int)-original_preview[region].astype(int)), axis=2)
            check(f"{name} translation in {route} processing preview",
                  np.count_nonzero(preview_diff > 40) > 100, int(np.count_nonzero(preview_diff > 40)))
    check("source project remains bilingual", project.studio_state["bilingual"]["mode"] == "bilingual")
    result["passed"] = all(c["passed"] for c in result["checks"])
    (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    app.processEvents()
    return 0


def start(window, output):
    """Name/video acceptance inside the same ordinary candidate executable."""
    import os, sys, traceback
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    def execute():
        path=output/'result.json'
        try:
            code=run(output,speaker_names=True)
            data=json.loads(path.read_text('utf8'))
        except Exception:
            code=1;data={'passed':False,'error':traceback.format_exc()}
        data.update(frozen=bool(getattr(sys,'frozen',False)),identity=load_build_identity().to_dict(),pid=os.getpid())
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
        window.result_exit_code=code
        def stopped():
            data['gui_shutdown']=True;path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(250,execute)
