"""Launch the released desktop with explicit, persistent container roots."""
from __future__ import annotations
import os
from pathlib import Path

def configure() -> None:
    defaults = {
        "2BYTEASR_INSTALL_ROOT": "/app",
        "2BYTEASR_USER_DATA_ROOT": "/config",
        "2BYTEASR_MODEL_ROOT": "/models",
        "2BYTEASR_RUNTIME_ROOT": "/config/runtimes",
        "HF_HOME": "/config/cache/huggingface",
        "TORCH_HOME": "/config/cache/torch",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    for key in ("2BYTEASR_USER_DATA_ROOT", "2BYTEASR_MODEL_ROOT", "2BYTEASR_RUNTIME_ROOT"):
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)

def seed_settings(path: Path | None = None) -> None:
    from copy import deepcopy
    from twobyteasr.settings import DEFAULT_SETTINGS, project_settings_path, save_runtime_settings
    path = path if path is not None else project_settings_path()
    if path.exists():
        return
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["models"].update(
        primary_asr_backend="api", speaker_source="native",
        qwen_asr_api_provider="mosi_moss_pro", qwen_asr_api_protocol="mosi_transcriptions",
        qwen_asr_api_model="moss-transcribe-diarize-pro", qwen_asr_api_url="https://api.mosi.cn/v1",
        firered_asr_backend="qwen_aligner", qwen_asr_backend="off")
    settings["switches"]["enable_firered_boundary_refinement"] = True
    for key in ("enable_qwen_asr_reference",
                "enable_ai_polish", "use_ai_grouping"):
        settings["switches"][key] = False
    save_runtime_settings(settings, project_root=path.parent)

def main() -> int:
    configure()
    seed_settings()
    from quick_start import main as desktop_main
    return desktop_main()

if __name__ == "__main__":
    raise SystemExit(main())
