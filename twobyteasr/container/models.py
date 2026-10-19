"""Use the 0.8.1 locked downloader for container-supported CPU models."""
from __future__ import annotations
import argparse
from pathlib import Path

SUPPORTED_MODELS = frozenset({"sensevoice", "paraformer", "funasr_nano",
                              "qwen_aligner", "ja_ctc_aligner", "whisper_turbo"})

def prepare(keys: list[str], source: str, destination: Path) -> None:
    unsupported = set(keys) - SUPPORTED_MODELS
    if not keys or unsupported:
        raise ValueError("Docker CPU 版支持 Qwen3 强制对齐、日语 CTC、Whisper、Paraformer、SenseVoice、Fun-ASR Nano；此模型需要其他运行环境。")
    from twobyteasr.model_integrity import locked_model, verify_model_files
    from twobyteasr.repository_download import download_model
    from twobyteasr.runtime_paths import detect_install_root
    root = detect_install_root()
    for key in dict.fromkeys(keys):
        spec = locked_model(key, root=root)
        target = destination / Path(spec["path"].replace("\\", "/")).name
        print(f"[Docker] 下载并校验 {key}: {target}", flush=True)
        download_model(model_key=key, spec=spec, destination=target, mode=source,
                       staging_root=destination / ".download-staging")
        verify_model_files(key, target, root=root)
        print(f"[Docker] {key} 已通过锁定文件校验", flush=True)

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", default="sensevoice")
    parser.add_argument("--source", choices=["HF_OFFICIAL", "HF_MIRROR", "MODELSCOPE", "AUTO"], default="AUTO")
    parser.add_argument("--models", type=Path, default=Path("/models"))
    args = parser.parse_args(argv)
    from .launch import configure
    configure()
    prepare([key.strip() for key in args.keys.split(",") if key.strip()], args.source, args.models)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
