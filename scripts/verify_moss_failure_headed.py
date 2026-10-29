"""Replay synthetic MOSS failures in the normal window on a private desktop."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--exe', type=Path, help='Verify the normal frozen entry point')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('Choose a fresh output under tmp')
    out.mkdir(parents=True)
    sys.path.insert(0, str(root))
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    cases = []
    for name, cause, expected in (
        ('context', 'Prompt/audio sequence exceeds max_length=131072', '音频超过单次输入上限'),
        ('page-file', 'OSError: [WinError 1455] 页面文件太小，无法完成操作。', '系统管理的大小'),
        ('cuda', 'torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 672 MiB', '显存分配失败'),
        ('dependency', "ModuleNotFoundError: No module named 'moss_transcribe_diarize'", '运行环境'),
        ('unknown', '', '未返回具体异常'),
    ):
        cases.append(dict(name=name, cause=cause, expected=expected))
    (out / 'failure-cases.json').write_text(json.dumps(cases, ensure_ascii=False), 'utf8')
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    guard = out / 'empty.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='', duration_ms=0)), guard)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='moss-full-context',
               TWOBYTEASR_STARTUP_PROJECT=str(guard), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    exe = args.exe.resolve() if args.exe else None
    command = [str(exe)] if exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    code = run_on_desktop(command, cwd=root,
                          env=env, output=out / 'process', timeout=150)
    result_path = out / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {'passed': False}
    result['process_exit'] = code
    # The normal GUI returns QueueResult.exit_code on shutdown. These are all
    # intentionally failed tasks, so 1 is required; a crash is not accepted.
    result['expected_process_exit'] = 1
    identity_ok = not exe or (result.get('packaged') and Path(result.get('executable', '')).resolve() == exe)
    result['passed'] = bool(result.get('passed') and code == 1 and identity_ok and len(result.get('checks', [])) == 5)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
