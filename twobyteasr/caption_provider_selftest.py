"""Frozen/source, network-free test of the static design and style contracts."""
from pathlib import Path
import json
import os
import sys


def main(output):
    out=Path(output).resolve()
    if not out.is_relative_to(Path.cwd()/'tmp'):raise ValueError('self-test output must be under cwd/tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    import socket
    def forbidden(*args,**kwargs):raise RuntimeError('network forbidden in caption self-test')
    socket.socket.connect=forbidden
    from .build_identity import load_build_identity
    from .caption_design_trials import local_specs,compile_web_theme,CaptionPreferences
    from .runtime_paths import detect_install_root
    from .caption_arbitration import arbitrate
    from .studio_project import SubtitleProject,StudioMedia,StudioCue
    from .studio_revisions import StudioRevisionStore
    from .ass_compiler import compile_ass,compile_ass_revision
    from .visual_snapshot import build_visual_cue_snapshot
    from .caption_creative_pipeline import ThemeLedger,digest,PRIORITY
    specs=local_specs();themes=[compile_web_theme(spec) for spec in specs]
    prefs=CaptionPreferences(detect_install_root()/'docs/design/caption-preferences.json').read()
    project=SubtitleProject(media=StudioMedia('selftest.mp4',duration_ms=6000),
        cues=[StudioCue('c',0,5000,'只要打PVP顺手就给他做完了',appearance_override={'font_size':180,'shadow':5})])
    project.validate();snapshot=build_visual_cue_snapshot(project,'c')
    consensus=arbitrate('哦他有送球的他有送球的','这还有送球的还有送球的','啊还有送球的还有送球的')
    checks={'three_specs':len(themes)==3,'single_semantic_text':all(theme['cueHtml'].count('data-semantic-text')==1 for theme in themes),
        'no_script':all('<script' not in theme['cueHtml'] for theme in themes),'negative_preferences':len(prefs['negative_rules'])>=4,
        'source_revision_parity':compile_ass(project)==compile_ass_revision(StudioRevisionStore(project).render),
        'font_loaded':snapshot.resolved_caption.font_loaded,'wrapped_inside_safe_width':snapshot.resolved_caption.measured_width<=snapshot.resolved_caption.max_width,
        'font_size_180_retained':snapshot.resolved_caption.style.font_size==180,
        'two_display_lines':snapshot.resolved_caption.line_count==2,
        'fragment_consensus':consensus['selected_text']=='哦还有送球的还有送球的'}
    raw='  Balatro 原始要求\n不能改写 '
    ledger=ThemeLedger(out/'creative-ledger',raw)
    checks['raw_prompt_exact']=ledger.value['raw_user_prompt']==raw and ledger.value['raw_prompt_hash']==digest(raw)
    checks['priority_raw_first']=PRIORITY[0]=='raw_user_prompt' and PRIORITY[-1]=='local_defaults'
    checks['previous_three_rejected']=len(prefs.get('trial_runs',[]))==3 and all(r.get('user_rating')==3 and r.get('accepted') is False for r in prefs['trial_runs'])
    checks['accepted_history_separate']=bool(prefs.get('accepted_history')) and not prefs['choices']
    try:ledger.stage('invalid-contract',{'theme':'Crystal'},require_semantics=True)
    except ValueError:checks['lost_balatro_stops']=True
    else:checks['lost_balatro_stops']=False
    result={'passed':all(checks.values()),'checks':checks,'identity':load_build_identity().to_dict(),'requests':0,
        'preferences_choices':len(prefs['choices']),'preferences_trial_runs':len(prefs.get('trial_runs',[]))}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1
