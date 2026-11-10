"""Opt-in combined Home B and subtitle-task audit in the normal application."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def install_guards():
    from .translation_requests_audit import install_guards as install
    install()


def check_home(window, output, check, settle):
    import ctypes
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication
    from ..app.ui_recognition import RecognitionRoleCard
    from ..design.theme_manager import apply_theme
    window._ensure_recognition_page()
    window._return_to_settings()
    settle(.5)
    cards = [card for card in window.findChildren(RecognitionRoleCard) if card.isVisible()]
    check('three Home role cards visible', len(cards) == 3)
    primary = next(card for card in cards if card.role == 'primary')
    # Exercise the real display formatter with an explicitly synthetic cloud label.
    primary.set_state('MOSS Pro 云端 · moss-transcribe-diarize-pro', '在线', '未配置', 'warn')
    records = []
    for theme in ('warm', 'grape'):
        apply_theme(theme, QApplication.instance())
        settle(.5)
        cards = [card for card in window.findChildren(RecognitionRoleCard) if card.isVisible()]
        primary = next(card for card in cards if card.role == 'primary')
        primary.set_state('MOSS Pro 云端 · moss-transcribe-diarize-pro', '在线', '未配置', 'warn')
        settle(.25)
        tops = [card.model_label.mapTo(window, QPoint()).y() for card in cards]
        check(theme+' role names aligned', max(tops)-min(tops) <= 2)
        check(theme+' cloud name and model split', primary.model_label.text() == 'MOSS Pro 云端'
              and primary.model_sub_label.text() == 'moss-transcribe-diarize-pro')
        check(theme+' full Home screenshot', window.grab().save(str(output/(f'home-{theme}.png'))))
        popup_results = []

        def capture_popup(label):
            popup = QApplication.activePopupWidget()
            passed = popup is not None
            preference = ctypes.c_int()
            status = -1
            if popup is not None:
                status = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    ctypes.c_void_p(int(popup.winId())), 33, ctypes.byref(preference), ctypes.sizeof(preference))
                passed = passed and popup.grab().save(str(output/(f'home-{theme}-{label}.png')))
                popup.close()
            popup_results.append(dict(label=label, visible=passed, dwm_status=status, corner=preference.value))

        QTimer.singleShot(180, lambda: capture_popup('menu'))
        window.project_profile_manage.click()
        settle(.25)
        window.recognition_mode_combo.showPopup()
        settle(.2)
        capture_popup('combo')
        check(theme+' actual menu and combo opened', len(popup_results) == 2 and all(row['visible'] for row in popup_results))
        if sys.getwindowsversion().build >= 22000:
            check(theme+' native rounded corners', all(row['dwm_status'] == 0 and row['corner'] == 2 for row in popup_results))
        records.append(dict(theme=theme, name_y=tops, popups=popup_results))
    (output/'home-result.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    from types import SimpleNamespace
    from unittest.mock import patch
    from ..projects.studio_project import SubtitleProject, StudioCue, StudioMedia
    from ..subtitle_rules.sentence_refine import refine_cues_with_llm
    for separator in ('', ' '):
        inputs = []
        def keep_ranges(messages, **kwargs):
            payload = json.loads(messages[-1]['content'])
            inputs.append(payload['cues'])
            return json.dumps({'results': [dict(cue_id=row['cue_id'], action='keep') for row in payload['cues']]})
        cues = [StudioCue('en-a', 0, 2000, 'This is a complete sentence.'+separator),
                StudioCue('en-b', 2100, 4000, 'Here is another sentence.')]
        project = SubtitleProject(media=StudioMedia(path='fixture'), cues=cues,
                                  generation_metadata={'language': {'code': 'en'}})
        with patch('twobyteasr.providers.ai_providers.provider_for_stage',
                   lambda *args, **kwargs: SimpleNamespace(complete=keep_ranges)):
            result = refine_cues_with_llm(cues, project=project,
                runtime_settings={'models': {'group_model': 'fixture'}}, boundary_only=True)
        check('English exact spacing preserved '+repr(separator), result.llm_status == 'completed'
              and len(inputs) == 1 and ''.join(unit.cue.text for unit in result.ranges) == ''.join(cue.text for cue in cues)
              and len(result.ranges) == (1 if separator else 2))


    mixed_cues = [StudioCue('mix-a', 0, 2000, '先go.'), StudioCue('mix-b', 2100, 4000, 'next now.')]
    mixed_project = SubtitleProject(media=StudioMedia(path='fixture'), cues=mixed_cues,
                                   generation_metadata={'language': {'code': 'zh'}})
    with patch('twobyteasr.providers.ai_providers.provider_for_stage',
               lambda *args, **kwargs: SimpleNamespace(complete=keep_ranges)):
        mixed_result = refine_cues_with_llm(mixed_cues, project=mixed_project,
            runtime_settings={'models': {'group_model': 'fixture'}}, boundary_only=True)
    check('Mixed-language source edges preserve word separation', mixed_result.llm_status == 'completed'
          and len(mixed_result.ranges) == 2)


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        import importlib.util
        import traceback
        from ..runtime_paths import detect_install_root
        from ..diagnostics.build_identity import load_build_identity
        source = detect_install_root()/'scripts/verify_subtitle_tasks_headed.py'
        spec = importlib.util.spec_from_file_location('combined_subtitle_tasks_audit', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        code = 1
        try:
            code = module.child(output, window=window)
        except Exception:
            (output/'audit-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            window.close()
        path = output/'result.json'
        result = json.loads(path.read_text('utf-8')) if path.exists() else {}
        result.update(checks_passed=result.get('passed', 0), passed=code == 0 and result.get('failed', 1) == 0,
                      entry='frozen' if getattr(sys,'frozen',False) else 'quick_start.main',
                      executable=sys.executable, pid=os.getpid(), identity=load_build_identity().to_dict())
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        QApplication.instance().exit(code)

    QTimer.singleShot(600, execute)
