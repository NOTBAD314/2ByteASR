"""Build the small, pinned 0.7.5 MOSS worker patch; never use the generic hotfix."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ORIGINAL_SHA256 = 'a84ebbfeed5197b5a900c80343c1866d9d3006d1d774d5c3eeca7783fbab850c'


def build(original, patched, output):
    baseline = original.read_bytes()
    candidate = patched.read_bytes()
    if hashlib.sha256(baseline).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Original must be the published 0.7.5 worker')
    # Fail closed if a caller passes the shared development worker. The package
    # must contain just this correction, not unrelated, unreleased changes.
    old = baseline.decode('utf8').replace('\r\n', '\n')
    new = candidate.decode('utf8').replace('\r\n', '\n')
    start, end = new.index('def planning_prompt_length('), new.index('def prompt_inputs(')
    reversed_change = (new[:start] + new[end:]).replace(
        'full_prompt = planning_prompt_length(processor, len(audio), messages)',
        'full_inputs, full_prompt = prompt_inputs(processor, audio, messages, context_limit)')
    reversed_change = reversed_change.replace(
        '    first_inputs = None\n    chunks, windows, attempts, splits',
        '    first_inputs = full_inputs if plan["count"] == 1 else None\n    del full_inputs\n    chunks, windows, attempts, splits', 1)
    if reversed_change != old:
        raise ValueError('Patched worker contains changes beyond this fix')
    compile(new, 'moss_worker.py', 'exec')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'moss_worker.py').write_bytes(candidate)
    manifest = dict(version='0.7.5', patch='moss-long-audio-20261017',
                    original_sha256=ORIGINAL_SHA256,
                    patched_sha256=hashlib.sha256(candidate).hexdigest())
    (output / 'patch.json').write_text(json.dumps(manifest, indent=2), 'utf8')
    installer = Path(__file__).with_name('apply_moss_long_audio_hotfix.ps1').read_text('utf-8-sig')
    (output / 'apply.ps1').write_text(installer, 'utf-8-sig')  # Windows PowerShell 5 reads Chinese with BOM.
    for name, switch in [('install', ''), ('restore', ' -Restore')]:
        bat = ('@echo off\r\nsetlocal\r\nset "INSTALL_DIR="\r\n'
               'if not "%~1"=="" set "INSTALL_DIR=%~dp1"\r\n'
               'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1" -InstallDir "%INSTALL_DIR%"'
               + switch + '\r\nset "RESULT=%ERRORLEVEL%"\r\npause\r\nexit /b %RESULT%\r\n')
        (output / (name + '.cmd')).write_bytes(bat.encode('ascii'))
    (output / '使用说明.txt').write_text(
        '2ByteASR 0.7.5 长录播修复（2026-10-17）\n\n'
        '1. 完全退出 2ByteASR，把补丁解压到普通文件夹。\n'
        '2. 双击 install.cmd，等到显示“修复完成”。\n'
        '3. 重开软件，点击“重试失败项”；找不到原任务时重新放入视频开始识别。\n\n'
        '如果提示找不到软件：右键桌面快捷方式 → 打开文件所在的位置，'
        '把真正的 2ByteASR.exe 拖到 install.cmd 上（不要拖快捷方式）。\n'
        '只支持原始 0.7.5，安装前校验并备份 workers/moss_worker.py。'
        '不改模型、配置、工程、其他程序文件，不用重新下载模型。\n'
        '需要恢复原版时，退出软件并双击 restore.cmd；自定义安装位置同样拖入 EXE。\n'
        '只修复长音频在自动分段前触发 max_length=131072 的问题；不是完整版本升级。\n', 'utf-8-sig')
    archive = output.with_name(output.name + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            bundle.write(path, output.name + '/' + path.name)
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '\n', 'ascii')
    print(json.dumps({'zip': str(archive), 'size': archive.stat().st_size, **manifest}))
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--patched', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.original, args.patched, args.output)
