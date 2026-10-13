"""Fixed, isolated in-process smoke gates; never a desktop acceptance claim."""
from __future__ import annotations
import copy, json, sys, traceback
from pathlib import Path

def start(window, output):
    from PySide6.QtCore import QTimer
    from .studio_acceptance_audit import require
    from .build_identity import load_build_identity
    result={'runtime':'frozen' if getattr(sys,'frozen',False) else 'source',
            'executable':sys.executable,'build':vars(load_build_identity()),'checks':{},'scope':'offscreen in-process smoke; not desktop acceptance'}
    def check(name, value):
        result['checks'][name]=bool(value);require(value,name)
    def run():
        try:
            from .studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
            from .studio_edit_sequence import sequence_of, projected_cues
            from .studio_edit_commands import ripple_trim_command
            from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions, verify_subtitle_artifact
            from .studio_analysis_request import begin_request, current_request, cancel_request
            from types import SimpleNamespace
            p=SubtitleProject(media=StudioMedia(path=str(output/'synthetic.mp4'),duration_ms=60000),
                cues=[StudioCue('later',35000,37000,'中文😀\r\n第二行')])
            p.validate();sequence_of(p).video_track_locked=False
            canonical=copy.deepcopy(p.cues)
            cmd=ripple_trim_command(p,'start',30000);cmd.redo()
            check('A02_canonical_projected',p.cues==canonical and projected_cues(p)[0].start_ms==5000)
            cmd.undo();cmd.redo()
            loaded=load_project(save_project(p,output/'reopen.2byteproj'))
            check('A02_save_reopen',loaded.cues==canonical and projected_cues(loaded)[0].start_ms==5000)
            artifacts=export_subtitle_artifacts(loaded,output/'subtitles','synthetic',SubtitleExportOptions(frozenset({'srt','ass','json','txt'})))
            expected=copy.copy(loaded);expected.cues=projected_cues(loaded)
            check('G02_four_formats_readback',len(artifacts)==4 and all(verify_subtitle_artifact(a,expected).valid for a in artifacts))
            page=SimpleNamespace(project=p,session=SimpleNamespace(generation=1),_close_requested=False)
            request=begin_request(page,'highlight')
            check('A01_current_request',current_request(page,'highlight',request))
            page.project=loaded
            check('A01_stale_request',not current_request(page,'highlight',request))
            cancel_request(page,'highlight')
            check('A01_cancelled_request',not current_request(page,'highlight',request))
            from .web_theme import sanitize_css, sanitize_html
            for name, call in [('css',lambda:sanitize_css('.x{background:image-set("http://127.0.0.1:9/trap" 1x)}',section='cue')),
                               ('svg',lambda:sanitize_html('<svg><rect fill="url(\'file:///C:/synthetic.svg\')"/></svg>',section='cue'))]:
                try:call()
                except ValueError:check('G01_'+name,True)
                else:check('G01_'+name,False)
            from .runtime_paths import detect_install_root
            from .advanced_renderer import _export_browser
            check('G03_bundled_browser',_export_browser(detect_install_root()/'renderer',web=True).is_file())
            legacy=window.legacy
            check('D01_real_save',legacy.add_learned_mapping('测试','synthetic-old','synthetic-new'))
            check('D01_duplicate',legacy.add_learned_mapping('测试','synthetic-old','synthetic-new') is False)
            from .llm_config import AI_SERVICE_SPECS
            from .asr_provider_snapshot import resolve_provider_snapshot
            for service, model in [('deepseek','deepseek-chat'),('gemini','gemini-2.5-flash')]:
                spec=AI_SERVICE_SPECS[service]
                endpoint=dict(service=service,provider=spec['provider'],transport=spec['transport'],base_url=spec['base_url'],model=model,protocol='auto')
                profile=window.profile_store.create('synthetic-'+service,llm_config=dict(polish=endpoint,group=endpoint,unified=True,use_ai_grouping=True))
                check('D03_apply_'+service,window._apply_project_profile(profile,mark_used=False))
                actual=resolve_provider_snapshot(legacy.RUNTIME_SETTINGS).endpoint()
                check('D03_identity_'+service,actual['model']==model and actual['base_url'].rstrip('/')==spec['base_url'].rstrip('/'))
            result['passed']=True
        except Exception:
            result['passed']=False;result['error']=traceback.format_exc()
        finally:
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            window.close()  # normal close_ready cleanup; no QApplication.quit
    QTimer.singleShot(1500,run)
