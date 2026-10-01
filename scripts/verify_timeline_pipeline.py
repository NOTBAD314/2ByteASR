"""Real pipeline on an isolated edit, with read-only application credentials."""
import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    parser = argparse.ArgumentParser()
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--speaker-source",choices=("provider","moss","auto","ecapa","filetrans"),default="moss")
    parser.add_argument('--current-api', action='store_true', help='Use the exact configured API without substituting a model')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/"tmp"):
        raise ValueError("Output must stay in workspace tmp")
    out.mkdir(parents=True,exist_ok=True)
    source = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "2ByteASR"
    from twobyteasr import settings, llm_config
    raw = json.loads((source/settings.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    config,_ = settings._merge_known_settings(settings.DEFAULT_SETTINGS,raw)
    if not args.current_api:
        config["models"].update(primary_asr_backend="api",qwen_asr_backend="api",
            qwen_asr_api_provider="openrouter",qwen_asr_api_protocol="openrouter_verbose_json",
            qwen_asr_api_model="microsoft/mai-transcribe-2",qwen_asr_api_url="https://openrouter.ai/api/v1/audio/transcriptions")
    if args.speaker_source=='filetrans':
        config['models'].update(primary_asr_backend='api',qwen_asr_backend='api',
            qwen_asr_api_provider='qwen_filetrans',qwen_asr_api_protocol='dashscope_filetrans',
            qwen_asr_api_model='qwen-audio-3.0-asr-flash-filetrans',
            qwen_asr_api_url='https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription')
    reader = llm_config._read_secrets
    llm_config._read_secrets = lambda: reader(read_only_path=source/"secrets.dat")
    os.environ.update(LOCALAPPDATA=str(out/"local"),APPDATA=str(out/"roaming"))
    os.environ["2BYTEASR_USER_DATA_ROOT"] = str(out/"data")
    settings.stable_settings_root = lambda: out/"config"
    settings.load_runtime_settings = lambda *a,**k: (copy.deepcopy(config),str(source/settings.SETTINGS_FILENAME),[])
    from twobyteasr.studio_project import load_project,save_project
    from twobyteasr.recognition_input import capture_recognition_snapshot
    project = load_project(args.project)
    fixture = save_project(project,out/"fixture.2byteproj")
    snapshot = capture_recognition_snapshot(project,fixture)
    from twobyteasr.service import run_media_queue,RunOptions,CancellationToken
    token = CancellationToken()
    timeout = threading.Timer(480,token.cancel)
    timeout.daemon = True
    timeout.start()
    try:
        result = run_media_queue([project.media.path], RunOptions(studio_project_path=str(fixture),
            recognition_snapshot_json=json.dumps(snapshot,ensure_ascii=False),speaker_source=args.speaker_source),
            cancel_token=token)
        (out/"result.json").write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2),encoding="utf-8")
        print("RESULT",result.exit_code,flush=True)
        return result.exit_code
    finally:
        timeout.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
