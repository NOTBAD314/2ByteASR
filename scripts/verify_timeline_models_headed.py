"""Run timeline-model controls through the normal source or frozen application."""
import argparse
import shutil
import json
import os
from pathlib import Path
import sys

from isolated_windows_desktop import run_on_desktop

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--scenario", default="timeline-models", choices=["timeline-models","ultra-alignment","ultra-upgrade"])
    parser.add_argument("--models-from",type=Path)
    parser.add_argument("--runtime-from",type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Use a fresh directory under tmp/")
    out.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    if args.scenario in {'ultra-alignment','ultra-upgrade'}:
        from twobyteasr.storage.settings import DEFAULT_SETTINGS
        import copy
        old=copy.deepcopy(DEFAULT_SETTINGS);old['models']['firered_asr_backend']='qwen_aligner';old['models']['qwen_alignment_profile']='official-v1'
        old['switches']['use_ja_ctc_aligner']=True
        (out/'config').mkdir(exist_ok=True)
        (out/'config/2byteasr_settings.json').write_text(json.dumps(old,ensure_ascii=False),'utf8')
        os.environ['TWOBYTEASR_AUDIT_OWNS_QWEN_PROOF']='1'
    if args.scenario in {'ultra-alignment','ultra-upgrade'}:
        if args.models_from is None or args.runtime_from is None:
            raise ValueError('Ultra audit requires explicit model/runtime fixture roots')
        def stage_tree(source,target):
            for item in source.rglob('*'):
                if not item.is_file() or '__pycache__' in item.parts:
                    continue
                destination=target/item.relative_to(source)
                if not destination.resolve().is_relative_to(out):
                    raise ValueError('Fixture staging escaped output')
                destination.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(item,destination)
                except OSError:shutil.copy2(item,destination)
        for folder in ('Qwen3-ForcedAligner-0.6B','Qwen3-ForcedAligner-Ultra','Qwen3-ForcedAligner-Ultra-LocalHead'):
            stage_tree(args.models_from.resolve()/folder,out/'models'/folder)
        stage_tree(args.runtime_from.resolve(),out/'runtimes/main')
        os.environ['2BYTEASR_RUNTIME_ROOT']=str(out/'runtimes')
        os.environ['TWOBYTEASR_MAIN_PYTHON']=str(out/'runtimes/main/Scripts/python.exe')
        os.environ['TWOBYTEASR_MANAGED_RUNTIME_ONLY']='1'
        os.environ['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY']='1'
        os.environ['TWOBYTEASR_ALIGNER_DEVICE']='cuda'
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    project = out / "fixture.2byteproj"
    if args.scenario in {'ultra-alignment','ultra-upgrade'}:
        sample=out/'speech.wav';shutil.copy2(ROOT/'assets/diagnostics/speech_en.wav',sample)
        fixture=SubtitleProject(media=StudioMedia(path=str(sample),display_name='Offline alignment fixture',duration_ms=5974))
        fixture.validate();data=fixture.to_dict()
        data['media_pool'][0]['audio_metadata']={'has_audio':True,'channels':1,'sample_rate':16000,'stream_index':0}
        data['media_pool'][0]['video_metadata']={'has_video':False}
        data['render_settings']['_cue_domain']='timeline'
        data['generation_metadata']['language']={'code':'en','requested':'en'}
        data['cues']=[dict(id='ultra-fixture',start_ms=100,end_ms=5600,
            text='Hello this is a local speech recognition test the weather is sunny today',speaker_id='S00')]
        fixture=SubtitleProject.from_dict(data)
        save_project(fixture,project)
    else:
        save_project(SubtitleProject(media=StudioMedia(path="", display_name="Model selection fixture", duration_ms=0)), project)
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONUTF8="1",
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario,
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE",
                "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", "TWOBYTEASR_STARTUP_LEAVE_STUDIO"):
        env.pop(key, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=240)
    path = out / "result.json"
    result = json.loads(path.read_text("utf-8")) if path.exists() else {}
    passed = code == 0 and result.get("passed") and result.get("gui_shutdown")
    print(json.dumps(dict(passed=bool(passed), checks=len(result.get("checks", [])), exit=code,
                         error=result.get("error")), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
