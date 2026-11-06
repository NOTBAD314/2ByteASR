"""Final frozen-package checks for issues 12–15; owned data, no AI requests."""
import copy
import json
import os
from pathlib import Path
import sys
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from unittest.mock import patch
    result = dict(passed=False, checks=[], frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable)

    def save():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        save()
        if not value:
            raise RuntimeError(name+': '+str(detail))

    def run():
        import subtitle_core as core
        from PIL import ImageFont
        from ..projects import studio_project as projects
        from ..caption_style import subtitle_stacking
        from ..system.environment import check_worker_dependencies
        from ..providers.asr_provider_snapshot import restore_source_text
        from ..subtitle_rules import grouping
        from ..subtitle_rules.cue_cleanup import prepare_effective_sources, drop_placeholder_source_rows
        from ..subtitle_rules.grouping_contract import validate_grouping_result
        from ..exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
        try:
            check('frozen normal app', result['frozen'])
            with patch.multiple(core, PRIMARY_ASR_BACKEND='qwen_local', QWEN_ASR_BACKEND='sensevoice', FIRERED_ASR_BACKEND='qwen_aligner'):
                core.check_runtime()
            check('real bundled GUI dependencies pass with external-engine selections', True)
            check('Pillow native font measurement works', ImageFont.load_default(size=16).getbbox('字幕')[2]>0)
            check('GUI does not load qwen_asr engine', 'qwen_asr' not in sys.modules)
            workers=json.loads((output/'workers.json').read_text('utf8'))
            for name in ['empty','present']:
                python=workers[name]
                try:
                    probe=check_worker_dependencies('main', python, {'qwen-asr':'qwen_asr'})
                except RuntimeError as exc:
                    check('missing worker dependency names selected interpreter', name=='empty' and python in str(exc) and '模型工坊' in str(exc), str(exc))
                else:
                    check('presence probe uses selected worker without importing engine', name=='present' and probe.ok and Path(probe.detail['interpreter'])==Path(python))
            media=output/'fixture.mp4'
            old=projects.project_from_runtime_cues(str(media), [core.SubtitleCue(1,0,1,'原字幕')], initialize_layout=False)
            target=output/'delivery/project.2byteproj';projects.save_project(old,target);before=target.read_bytes()
            for failure in [ModuleNotFoundError("No module named 'PIL'"), ValueError('controlled layout failure')]:
                with patch.object(subtitle_stacking, 'initialize_project_layout', side_effect=failure):
                    delivered=projects.create_studio_outputs(str(media), [core.SubtitleCue(1,1,2,'识别已完成')], txt_path='', target_project_path=str(target))
                check('layout failure preserves prior project', target.read_bytes()==before and not delivered['project'], str(failure))
                recovered=projects.load_project(delivered['recovery_project'])
                check('layout failure writes reopenable recovery', recovered.cues[0].text=='识别已完成' and recovered.generation_metadata['delivery_recovery']['state']=='awaiting_save')
            with patch.object(projects, 'save_project', side_effect=OSError('controlled disk full')):
                delivered=projects.create_studio_outputs(str(media), [core.SubtitleCue(1,1,2,'识别已完成')], txt_path='', target_project_path=str(target))
            check('write failure preserves old file and exposes recovery', target.read_bytes()==before and not delivered['project'] and Path(delivered['recovery_project']).is_file())
            def row(n,text,a,b,speaker='S01'):
                return core.SpeechSegment(n,a,b,text,.8,[],speaker=speaker)
            def cue(n,text,a,b,speaker='S01'):
                return core.SubtitleCue(n,a,b,text,speaker=speaker)
            rows=[row(1,'啊',0,1),row(2,'<sil>',4,16.905)];cues=[cue(1,'啊',0,1),cue(2,'<sil>',4,16.905)];snapshot=copy.deepcopy(cues)
            check('valid provenance is unchanged', grouping._restore_grouped_source(rows,cues) and cues==snapshot)
            check('valid provenance is idempotent', grouping._restore_grouped_source(rows,cues) and cues==snapshot)
            rows=[row(1,'你好， “世界”',0,2)];cues=[cue(1,'你好',0,1),cue(2,'世界',1,2)]
            check('restoration preserves punctuation and opening quote', restore_source_text(rows,cues) and [c.text for c in cues]==['你好，','“世界”'] and validate_grouping_result(rows,cues))
            rows=[row(1,'<sil>',205.06,217.965),row(2,'i',206,207,'S02')]
            cues=[cue(1,'<s',205.06,209.362),cue(2,'i',209.362,213.663),cue(3,'l>',213.663,217.965),cue(4,'i',206,207,'S02')]
            stats=drop_placeholder_source_rows(cues,rows)
            check('placeholder fragments removed by exact source ownership', stats['rows']==1 and stats['cues']==3 and [(c.text,c.speaker) for c in cues]==[('i','S02')])
            check('remaining overlapping speaker has valid provenance', validate_grouping_result(rows,cues))
            original=[row(1,'正文',0,2),row(2,'<sil>',3,4),row(3,'<unk>',5,6)]
            effective=prepare_effective_sources(original,speech_regions=[])
            check('effective sources exclude markers before grouping', [x.text for x in effective]==['正文'] and len(original)==3)
            for text in ['<sil>','<unk>','x < y']:
                project=projects.project_from_runtime_cues(str(media),[cue(1,text,0,1)],initialize_layout=False)
                p=output/('manual-'+str(len(result['checks']))+'.2byteproj');projects.save_project(project,p)
                reopened=projects.load_project(p)
                artifact=export_subtitle_artifacts(reopened,output/'exports',p.stem,SubtitleExportOptions())[0]
                check('manual literal survives save/reopen/export', reopened.cues[0].text==text and text in artifact.path.read_text('utf8'),text)
            window.grab().save(str(output/'home.png'))
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            save()
            window.close()
            QTimer.singleShot(100,QApplication.instance().quit)
    def quit_receipt():
        result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(quit_receipt)
    QTimer.singleShot(500,run)
