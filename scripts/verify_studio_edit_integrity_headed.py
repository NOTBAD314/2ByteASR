"""Normal MainWindow, isolated profile/private Windows desktop, no provider calls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--count', type=int, default=4000)
    parser.add_argument('--restart', type=Path)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('Use a fresh directory under this checkout/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    fixture = out/'fixture.2byteproj'
    if args.restart:
        shutil.copyfile(args.restart/'saved-result.2byteproj', fixture)
        shutil.copyfile(args.restart/'expected.json', out/'expected.json')
        settings = args.restart/'config/2byteasr_settings.json'
        if settings.is_file():
            (out/'config').mkdir(exist_ok=True)
            shutil.copyfile(settings, out/'config/2byteasr_settings.json')
    else:
        media = out/'fixture.mp4'
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=0x213c58:s=1280x720:r=24:d=20', '-c:v', 'libx264', '-threads', '2',
            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(media)], check=True)
        from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
        from twobyteasr.subtitle_rules import subtitle_translation as st
        from twobyteasr.glossary.translation_terms import KEY, normalize
        p = SubtitleProject(StudioMedia(str(media), duration_ms=max(20000, args.count*2500), width=1280, height=720),
            cues=[StudioCue(f'cue-{i:05d}', i*2500, i*2500+1800, f'原文字幕第{i:05d}条',
                           speaker_id='S00', original_text=f'原文字幕第{i:05d}条') for i in range(args.count)],
            speakers=[StudioSpeaker('S00', '主播')], studio_state={'bilingual': {'mode': 'bilingual'}},
            generation_metadata={'language': {'code': 'zh'}, KEY: normalize(dict(enabled=True, selected_ids=['a', 'b'],
            libraries=[dict(id='a', name='鸣潮', source_language='ja', target_language='zh-Hans', terms=[
                dict(source='アリス', target='爱丽丝', aliases=[], context='人物')]),
                       dict(id='b', name='废案', source_language='ja', target_language='zh-Hans', terms=[
                dict(source='石', target='石头', aliases=[], context='')])]))})
        container = st._empty_container('en')
        container['records'] = {c.id: st._record(f'Translation line {i:05d}', c.text, origin=st.ORIGIN_MANUAL, target='en')
                                for i, c in enumerate(p.cues)}
        p.generation_metadata[st.RECORDS_KEY] = container
        p.generation_metadata[st.RENDER_KEY] = {key: value['text'] for key, value in container['records'].items()}
        save_project(p, fixture)
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-edit-integrity',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_MAIN_PYTHON=sys.executable, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
        TWOBYTEASR_EDIT_INTEGRITY_RESTART='1' if args.restart else '0',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out/'process', timeout=300)
    path = out/'result.json'
    result = json.loads(path.read_text('utf8')) if path.is_file() else {'passed': False, 'error': 'missing receipt'}
    result['exit_code'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), output=str(out), exit=code), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
