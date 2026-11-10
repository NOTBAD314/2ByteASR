"""Replay owned Studio operations with an independent process watchdog.

All writable state stays in a fresh source/tmp directory. The resource observer
runs in this parent process. Only the real Qt event path writes ui-heartbeat.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def write_json(path, value):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    temporary.replace(path)


def prepare_fixture(output, count, terms, seed):
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output / 'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.studio_search_fixture import make_project
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project

    media = output / 'numbered-1080p30.mp4'
    ffmpeg = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
    command = [str(ffmpeg), '-v', 'error', '-y', '-f', 'lavfi', '-i',
               'testsrc2=size=1920x1080:rate=30:duration=32', '-f', 'lavfi', '-i',
               'sine=frequency=440:sample_rate=48000:duration=32', '-vf',
               "drawtext=text='%{pts\\:hms}':fontsize=80:fontcolor=white:box=1:boxcolor=black:x=60:y=60",
               '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', '2',
               '-g', '120', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)]
    with (output / 'fixture-ffmpeg.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    content = make_project(count, terms, 24)
    project = SubtitleProject(
        StudioMedia(str(media), duration_ms=3600000 if count <= 3000 else 28800000,
                    width=1920, height=1080),
        cues=content.cues, speakers=content.speakers, styles=content.styles,
        generation_metadata=content.generation_metadata, asr_evidence=content.asr_evidence)
    project.project_id = hashlib.sha256(f'stability:{count}:{terms}:{seed}'.encode()).hexdigest()[:32]
    # A short real decoder input plus a long structural timeline is explicit.
    # Media-frame measurements stay within the real 32-second source.
    for index, cue in enumerate(project.cues):
        cue.start_ms = index * (project.media.duration_ms // count)
        cue.end_ms = cue.start_ms + min(1100, project.media.duration_ms // count - 1)
        cue.evidence_refs = [f'segment:{index}']
        characters = list(cue.text)
        span = (cue.end_ms-cue.start_ms)/max(1,len(characters))
        project.asr_evidence[f'segment:{index}'] = dict(text=cue.text,
            start=cue.start_ms/1000, end=cue.end_ms/1000,
            words=[dict(text=character, start=(cue.start_ms+part*span)/1000,
                        end=(cue.start_ms+(part+1)*span)/1000, probability=.96)
                   for part,character in enumerate(characters)])
    project_path = save_project(project, output / 'fixture.2byteproj', compact=True)
    alternate = json.loads(project_path.read_text('utf8'))
    alternate['project_id'] = hashlib.sha256(f'stability-alternate:{count}:{terms}:{seed}'.encode()).hexdigest()[:32]
    (output/'fixture-alternate.2byteproj').write_text(json.dumps(alternate,ensure_ascii=False,separators=(',',':')), 'utf8')
    entry = save_project(SubtitleProject(StudioMedia('')), output / 'entry.2byteproj')
    write_json(output / 'fixture.json', dict(seed=seed, cues=count, translations=count-2,
        source_duration_seconds=32, structural_duration_ms=project.media.duration_ms,
        terms=terms, evidence_words='one per Unicode code point', project_sha256=hashlib.sha256(project_path.read_bytes()).hexdigest(),
        media_sha256=hashlib.sha256(media.read_bytes()).hexdigest(), ffmpeg_command=command))
    return entry


def native_dump(pid, path):
    """Capture an owned process minidump before any timeout termination."""
    import ctypes
    from ctypes import wintypes as W
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    dbghelp = ctypes.WinDLL('dbghelp', use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    dbghelp.MiniDumpWriteDump.argtypes = [W.HANDLE, W.DWORD, W.HANDLE, W.DWORD,
                                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    dbghelp.MiniDumpWriteDump.restype = W.BOOL
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with path.open('wb') as stream:
            if not dbghelp.MiniDumpWriteDump(handle, pid, msvcrt.get_osfhandle(stream.fileno()),
                                             0x1000, None, None, None):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def observe(output, stop, timeout, silence):
    started = time.perf_counter()
    monitor = dict(pid=os.getpid(), independent_process=True, samples=0, stalls=[],
                   forced_end=False, errors=[], observed_pids=[])
    known = {}
    last_sequence = None
    sequence_since = started
    observed_stall = False
    next_gpu = started
    with (output / 'resources.jsonl').open('w', encoding='utf8') as log:
        while not stop.wait(.5):
            now = time.perf_counter()
            heartbeat = None
            try:
                heartbeat = json.loads((output / 'ui-heartbeat.json').read_text('utf8'))
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                pass
            pid = heartbeat.get('pid') if heartbeat else None
            if pid and pid not in known:
                try:
                    known[pid] = psutil.Process(pid)
                except psutil.NoSuchProcess:
                    pass
            rows = []
            for main in list(known.values()):
                try:
                    processes = [main, *main.children(recursive=True)]
                except psutil.NoSuchProcess:
                    continue
                for process in processes:
                    try:
                        memory = process.memory_info()
                        cpu = process.cpu_times()
                        io = process.io_counters()
                        rows.append(dict(pid=process.pid, name=process.name(), rss=memory.rss,
                            private=getattr(memory, 'private', None), cpu_seconds=cpu.user+cpu.system,
                            threads=process.num_threads(), handles=process.num_handles(),
                            read_bytes=io.read_bytes, write_bytes=io.write_bytes))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            sample = dict(monotonic=now, elapsed_seconds=now-started, processes=rows,
                          heartbeat=heartbeat)
            if now >= next_gpu:
                next_gpu = now + 10
                try:
                    gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used',
                                          '--format=csv,noheader,nounits'], capture_output=True,
                                          text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                    sample['whole_gpu'] = gpu.stdout.strip()
                except (OSError, subprocess.TimeoutExpired) as error:
                    sample['gpu_error'] = type(error).__name__
            log.write(json.dumps(sample, ensure_ascii=False)+'\n')
            log.flush()
            monitor['samples'] += 1
            if heartbeat:
                age = now-heartbeat['monotonic']
                sequence = heartbeat.get('completed')
                if sequence != last_sequence:
                    last_sequence, sequence_since = sequence, now
                if age >= 3 and not observed_stall:
                    evidence = dict(at=now, age_seconds=age, phase=heartbeat.get('phase'))
                    try:
                        dump = output / f'watchdog-{pid}-{len(monitor["stalls"])}.dmp'
                        native_dump(pid, dump)
                        evidence['dump'] = str(dump)
                    except OSError as error:
                        evidence['dump_error'] = str(error)
                    monitor['stalls'].append(evidence)
                    observed_stall = True
                if age < 1:
                    observed_stall = False
                # Stage progress and UI liveness are monitored independently.
                no_progress = now-sequence_since > timeout
                if age > silence or no_progress:
                    monitor['forced_end'] = True
                    monitor['reason'] = 'UI heartbeat timeout' if age > silence else 'task progress timeout'
                    for main in known.values():
                        try:
                            subprocess.run(['taskkill', '/PID', str(main.pid), '/T', '/F'],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        except OSError as error:
                            monitor['errors'].append(str(error))
                    break
            if log.tell() > 32 * 1024 * 1024:
                monitor['errors'].append('resource log exceeded 32 MiB budget')
                break
    monitor['observed_pids'] = list(known)
    monitor['elapsed_seconds'] = time.perf_counter()-started
    write_json(output / 'monitor.json', monitor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=2500)
    parser.add_argument('--terms', type=int, default=1000)
    parser.add_argument('--edits', type=int, default=200)
    parser.add_argument('--seeks', type=int, default=200)
    parser.add_argument('--opens', type=int, default=5)
    parser.add_argument('--media-count', type=int, choices=(0,100,500), default=0)
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--seed', type=int, default=20261109)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--inject-freeze', type=float, default=0)
    parser.add_argument('--silence-timeout', type=float, default=90)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        parser.error('fresh source/tmp output required')
    if args.count < 20 or min(args.edits, args.seeks, args.opens, args.seconds) < 0:
        parser.error('invalid workload')
    output.mkdir(parents=True)
    entry = prepare_fixture(output, args.count, args.terms, args.seed)
    configuration = vars(args).copy()
    configuration['output'] = str(output)
    configuration['exe'] = str(args.exe) if args.exe else None
    write_json(output / 'configuration.json', configuration)
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(output / 'profile'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='stability-performance',
        TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_MAIN_PYTHON=sys.executable,
        TWOBYTEASR_STARTUP_SIZE='1440x900', QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1',
        PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    stop = threading.Event()
    observer = threading.Thread(target=observe, args=(output, stop, 180, args.silence_timeout),
                                name='external-watchdog')
    observer.start()
    code = None
    try:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process',
                              timeout=max(900, args.seconds+1500))
    finally:
        stop.set()
        observer.join(10)
    path = output / 'result.json'
    result = json.loads(path.read_text('utf8')) if path.is_file() else dict(passed=False, error='missing UI receipt')
    result['process_exit'] = code
    monitor = json.loads((output / 'monitor.json').read_text('utf8'))
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0
                            and not monitor['forced_end'] and not monitor['errors'])
    result['monitor'] = monitor
    write_json(path, result)
    records = output / 'operations.jsonl'
    if records.is_file():
        with (output / 'operations.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=['sequence','name','input_at','received_at',
                'state_at','paint_at','handler_ms','completion_ms','status'])
            writer.writeheader()
            for line in records.read_text('utf8').splitlines():
                row = json.loads(line)
                writer.writerow({key:row.get(key) for key in writer.fieldnames})
    print(json.dumps(dict(passed=result['passed'], operations=result.get('completed'),
                          error=result.get('error'), process_exit=code), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
