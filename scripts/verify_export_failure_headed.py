"""Show the actual failure workspace on an isolated native Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):raise ValueError('Output must be under tmp/')
    output.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(ROOT))
    if not args.child:
        from isolated_windows_desktop import run_on_desktop
        env=dict(os.environ,QT_QPA_PLATFORM='windows',TWOBYTEASR_TEST_ROOT=str(output/'isolated'))
        return run_on_desktop([sys.executable,'-X','utf8',__file__,'--child','--output',str(output)],
                              cwd=ROOT,env=env,output=output/'process',timeout=60)
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase,QFont
    from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings
    app=QApplication([])
    identity=QFontDatabase.addApplicationFont(str(ROOT/'assets/fonts/SourceHanSansSC-Medium.otf'))
    family=QFontDatabase.applicationFontFamilies(identity)[0];app.setFont(QFont(family,10))
    original=StudioExportWorkspace._populate_encoders
    def encoders(self):
        self.encoder.clear();self.encoder.addItem('NVIDIA H.264','h264_nvenc');self.encoder.addItem('CPU H.264','libx264')
    StudioExportWorkspace._populate_encoders=encoders
    workspace=StudioExportWorkspace(SubtitleProject(media=StudioMedia('synthetic.mp4',duration_ms=54000)),'')
    job=RenderJob('synthetic.mp4','',str(output/'result.mp4'),RenderSettings(encoder='h264_nvenc'))
    job.export_context.update(diagnostics_path=str(output),requested_encoder='h264_nvenc',failure=dict(
        stage='encode',category='nvenc',reason='NvEncEncodePicture failed: device lost',encoder='h264_nvenc',
        returncode=-1,progress={'frame':'768','out_time_us':'26500000'},video_time_seconds=25.6,retry_cpu=True,
        suggestion='检查 NVIDIA 驱动和 GPU 占用，或选择“改用 CPU 编码…”返回设置。'))
    workspace._last_job=job
    workspace.resize(1100,700);workspace.show();app.processEvents()
    workspace._show_failure('NvEncEncodePicture failed: device lost\n\nfixture traceback')
    for _ in range(8):app.processEvents()
    checks=dict(title=workspace.failure_title.text()=='导出中断',
        reason='device lost' in workspace.failure_reason.text(),
        phase='视频编码' in workspace.failure_reason.text(),
        exit_code='-1' in workspace.failure_reason.text(),time='26.500' in workspace.failure_reason.text(),
        encoder='h264_nvenc' in workspace.failure_reason.text(),video_position='25.600' in workspace.failure_reason.text(),
        cpu_visible=workspace.cpu_retry_button.isVisible(),log_visible=workspace.diagnostics_button.isVisible())
    workspace.grab().save(str(output/'failure-wide.png'))
    workspace.resize(760,680);app.processEvents();workspace.grab().save(str(output/'failure-narrow.png'))
    checks['narrow_reason_inside']=workspace.failure_reason.geometry().bottom()<workspace.failure_page.height()
    workspace.cpu_retry_button.click();app.processEvents()
    checks['cpu_review']=workspace.pages.currentWidget() is workspace.setup_page and workspace.encoder.currentData()=='libx264'
    checks['no_auto_start']=not workspace._running
    checks['quality_review']='CRF' in workspace.actual_encoder_hint.text()
    checks['frozen_settings']=job.settings.encoder=='h264_nvenc'
    def invalid_target():raise ValueError('invalid new target')
    workspace.export_target=invalid_target
    workspace._start();app.processEvents()
    checks['fresh_failure']='invalid new target' in workspace.failure_reason.text() and 'device lost' not in workspace.failure_reason.text()
    checks['fresh_stage']='准备工程' in workspace.failure_reason.text()
    workspace._last_job=job
    workspace.pages.setCurrentWidget(workspace.exporting_page)
    workspace._apply_progress(48,{'stage':'encode','message':'连续合成字幕与视频并编码…','out_time_ms':'26500000','frame':'768','fps':'8.23'})
    before_stage=workspace._progress_payload['stage']
    workspace._progress({'notice':'实时预览已停止，成片继续编码。'})
    app.processEvents()
    checks['preview_warning_visible']=workspace.processing_info.isVisible() and '预览已停止' in workspace.processing_info.text()
    workspace.grab().save(str(output/'preview-warning.png'))
    checks['warning_preserves_stage']=workspace._progress_payload['stage']==before_stage
    checks['warning_not_clipped']=workspace.processing_info.height()>=workspace.processing_info.heightForWidth(workspace.processing_info.width())
    from dataclasses import replace
    import twobyteasr.exports.export_notification as notifications
    original_notify=notifications.notify_export_completed
    notifications.notify_export_completed=lambda *args:None
    real=json.loads((ROOT/'tmp/export-reliability-20261102/ordinary-final/result.json').read_text('utf8'))
    actual_output=Path(real['receipt']['output_path'])
    assert actual_output.is_relative_to(ROOT/'tmp') and actual_output.is_file()
    final_job=replace(job,output_path=str(actual_output),export_context=dict(
        diagnostics_path=str(output),preview_warning={'reason':'controlled preview warning'}))
    final_job.completion_metadata.update(real['receipt'])
    workspace._last_job=final_job
    workspace._show_success(str(actual_output));app.processEvents()
    checks['success_warning_visible']=workspace.success_page.error.isVisible() and '成片已完整校验' in workspace.success_page.error.text()
    from PySide6.QtWidgets import QScrollArea
    scrolls=([workspace.success_page] if isinstance(workspace.success_page,QScrollArea) else [])+workspace.success_page.findChildren(QScrollArea)
    for scroll in scrolls:scroll.ensureWidgetVisible(workspace.success_page.error)
    app.processEvents()
    workspace.grab().save(str(output/'success-preview-warning.png'))
    notifications.notify_export_completed=original_notify
    workspace.release_preview();workspace.close();app.processEvents()
    StudioExportWorkspace._populate_encoders=original
    (output/'result.json').write_text(json.dumps(dict(checks=checks,passed=all(checks.values())),ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
