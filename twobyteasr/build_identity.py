# SPDX-License-Identifier: GPL-3.0-only
"""Auditable build identity for source and packaged desktop launches."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


BUILD_METADATA_FILENAME = "2byteasr_build.json"

# The delivery and its fingerprint share this exclusion boundary. Historical
# license records stay included; retired executables, installers and vendors do not.
_RETIRED_DELIVERY_FILES = frozenset({
    'optional_model_worker.py',
    'requirements-diarizen.in', 'requirements-diarizen.lock',
    'requirements-vibevoice.in', 'requirements-vibevoice.lock',
    'scripts/prepare_optional_models.py',
    'twobyteasr/optional_models.py',
    'twobyteasr/optional_model_process.py',
    'twobyteasr/optional_model_details.py',
    'twobyteasr/optional_models_audit.py',
    'twobyteasr/optional_models_headed_audit.py',
})
_RETIRED_DELIVERY_ROOTS = ('third_party/DiariZen/', 'third_party/VibeVoice/')


def is_current_delivery_file(relative: str) -> bool:
    normalized = relative.replace('\\', '/')
    return (normalized not in _RETIRED_DELIVERY_FILES
            and not normalized.startswith(_RETIRED_DELIVERY_ROOTS))

_SOURCE_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".ps1",
    ".py",
    ".spec",
    ".ts",
    ".tsx",
}
_SOURCE_ROOTS = ("packaging/", "scripts/", "twobyteasr/", "assets/cover-templates/", "assets/gimp/", "assets/theme-examples/")
_SOURCE_FILES = {
    '.github/workflows/macos-experimental.yml',
    "packaging/version_info.txt",
    "LICENSE", "PROJECT_LICENSE.md", "SOURCE_DELIVERY.md", "BUILD_FROM_SOURCE.md",
    "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "installer/2ByteASR-frozen.iss",
    "assets/diagnostics/speech_en.wav",
    "glm_asr_worker.py",
    "canary_asr_worker.py",
    "firered_llm_worker.py",
    "firered_vad_worker.py",
    "moss_worker.py",
    "assets/gimp/cover-sessionrc",
    "third_party/cover-psd.cjs",
    "third_party/cover-psd-NOTICE.md",
    "third_party/cover-psd-LICENSE.txt",
    "third_party/cover-psd-pako-LICENSE.txt",
    "third_party/cover-psd-base64-LICENSE.txt",
    "assets/design-skills/2byteskill/SKILL.md",
    "assets/design-skills/subtitle-theme-aesthetics/SKILL.md",
    "assets/design-skills/references/miku.md",
    "assets/design-skills/references/minecraft.md",
    "assets/design-skills/abstract-caption.md",
    "assets/design-skills/balatro-caption.md",
    "assets/design-skills/material-caption.md",
    "assets/design-skills/noita-caption.md",
    "assets/design-skills/zelda-caption.md",
    "assets/design-references/balatro/manifest.json",
    "assets/design-references/balatro/reference-atlas.jpg",
    "assets/fonts/SourceHanSansSC-Heavy.otf",
    "assets/fonts/SourceHanSansSC-Medium.otf",
    "renderer/public/fonts/SourceHanSansSC-Heavy.otf",
    "renderer/public/fonts/SourceHanSansSC-Medium.otf",
    "assets/fonts/Cubic11.ttf",
    "assets/fonts/Cubic11-OFL.txt",
    "renderer/public/fonts/Cubic11.ttf",
    "renderer/public/fonts/Cubic11-OFL.txt",
    "docs/design/caption-preferences.json",
    "2byteasr_version.json",
    "dependencies.lock.json",
    "moss_firered_pipeline.py",
    "quick_start.py",
    "subtitle_core.py",
    "firered_aed_worker.py",
    "asr_api_worker.py",
    "requirements-main.txt",
    "qwen_asr_worker.py",
    "qwen_aligner_worker.py",
    "ctc_aligner_worker.py",
    "speaker_embed_worker.py",
}
_RENDERER_SOURCE_ROOTS = ("renderer/public/", "renderer/src/", "renderer/app/")
_RENDERER_SOURCE_FILES = {
    "LICENSE", "PROJECT_LICENSE.md", "SOURCE_DELIVERY.md", "BUILD_FROM_SOURCE.md",
    "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "installer/2ByteASR-frozen.iss",
    "renderer/process_policy.cjs",
    "renderer/package-lock.json",
    "renderer/package.json",
    "renderer/service.mjs",
    "renderer/render-overlays.mjs",
    "renderer/export-browser.mjs",
    "renderer/resource-boundary.mjs",
    "renderer/tsconfig.json",
}


@dataclass(frozen=True)
class BuildIdentity:
    app_version: str
    git_sha: str
    git_dirty: bool
    build_time: str
    build_channel: str
    packaged: bool
    executable_path: str
    source_sha256: str
    source_file_count: int

    @property
    def mode(self) -> str:
        return "packaged" if self.packaged else "source"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mode"] = self.mode
        return payload


def _run_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def _version_payload(root: Path) -> dict[str, object]:
    try:
        value = json.loads((root / "2byteasr_version.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_source_file(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    if not is_current_delivery_file(normalized):
        return False
    if normalized.startswith('licenses/optional-models/'):
        return True
    if normalized.startswith('assets/cover-templates/'):
        return Path(normalized).suffix.lower() in {'.psd','.xcf','.png','.json','.md'}
    if normalized in _SOURCE_FILES or normalized in _RENDERER_SOURCE_FILES:
        return True
    if normalized.startswith(_RENDERER_SOURCE_ROOTS):
        return Path(normalized).suffix.lower() in _SOURCE_EXTENSIONS
    return normalized.startswith(_SOURCE_ROOTS) and Path(normalized).suffix.lower() in _SOURCE_EXTENSIONS


def source_snapshot_files(root: Path) -> tuple[Path, ...]:
    listed = _run_git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    files: list[Path] = []
    for relative in listed.splitlines():
        if not _is_source_file(relative):
            continue
        candidate = root / relative
        if candidate.is_file():
            files.append(candidate)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix().lower()))


def source_snapshot_sha256(root: Path, files: Iterable[Path] | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in files if files is not None else source_snapshot_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        count += 1
    return digest.hexdigest(), count


def create_build_metadata(root: Path, *, channel: str = "") -> dict[str, object]:
    root = root.resolve()
    version = _version_payload(root)
    source_sha256, source_file_count = source_snapshot_sha256(root)
    status = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    return {
        "schema_version": 1,
        "app_version": str(version.get("version") or "unknown"),
        "git_sha": _run_git(root, "rev-parse", "HEAD") or "unknown",
        "git_dirty": bool(status),
        "build_time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "build_channel": channel or str(version.get("channel") or "unknown"),
        "source_sha256": source_sha256,
        "source_file_count": source_file_count,
    }


def write_build_metadata(root: Path, destination: Path, *, channel: str = "") -> dict[str, object]:
    payload = create_build_metadata(root, channel=channel)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _metadata_candidates(project_root: Path, executable_path: Path) -> tuple[Path, ...]:
    candidates = [executable_path.parent / BUILD_METADATA_FILENAME]
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        candidates.append(Path(bundle_root) / BUILD_METADATA_FILENAME)
    candidates.append(project_root / "build" / BUILD_METADATA_FILENAME)
    return tuple(candidates)


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


_DEFAULT_IDENTITY_CACHE: BuildIdentity | None = None


def invalidate_build_identity_cache() -> None:
    """构建/打包脚本写入新元数据后可调用；运行期身份不变无需失效。"""
    global _DEFAULT_IDENTITY_CACHE
    _DEFAULT_IDENTITY_CACHE = None


def load_build_identity(
    *,
    metadata_path: Path | None = None,
    packaged: bool | None = None,
    executable_path: Path | None = None,
    project_root: Path | None = None,
) -> BuildIdentity:
    # 默认调用（全部缺省参数）进程内缓存：源码模式下一次调用要跑
    # git status + 全源码 SHA256（~300ms），应用设置页曾每次打开重算两遍
    # 成为 ~1s 延迟主因。显式参数调用（打包/审计指定路径）不缓存。
    if metadata_path is None and packaged is None and executable_path is None and project_root is None:
        global _DEFAULT_IDENTITY_CACHE
        if _DEFAULT_IDENTITY_CACHE is not None:
            return _DEFAULT_IDENTITY_CACHE
        _DEFAULT_IDENTITY_CACHE = _compute_build_identity()
        return _DEFAULT_IDENTITY_CACHE
    return _compute_build_identity(
        metadata_path=metadata_path,
        packaged=packaged,
        executable_path=executable_path,
        project_root=project_root,
    )


def _compute_build_identity(
    *,
    metadata_path: Path | None = None,
    packaged: bool | None = None,
    executable_path: Path | None = None,
    project_root: Path | None = None,
) -> BuildIdentity:
    frozen = bool(getattr(sys, "frozen", False)) if packaged is None else bool(packaged)
    executable = (executable_path or Path(sys.executable)).resolve()
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    payload: dict[str, object] = {}
    if metadata_path is not None:
        payload = _read_metadata(metadata_path)
    elif frozen:
        for candidate in _metadata_candidates(root, executable):
            payload = _read_metadata(candidate)
            if payload:
                break
    if not payload:
        version = _version_payload(root)
        status = _run_git(root, "status", "--porcelain", "--untracked-files=all")
        source_sha256, source_file_count = source_snapshot_sha256(root)
        payload = {
            "app_version": str(version.get("version") or "unknown"),
            "git_sha": _run_git(root, "rev-parse", "HEAD") or "unknown",
            "git_dirty": bool(status),
            "build_time": "not-built",
            "build_channel": str(version.get("channel") or "source"),
            "source_sha256": source_sha256,
            "source_file_count": source_file_count,
        }
    return BuildIdentity(
        app_version=str(payload.get("app_version") or "unknown"),
        git_sha=str(payload.get("git_sha") or "unknown"),
        git_dirty=bool(payload.get("git_dirty", False)),
        build_time=str(payload.get("build_time") or "unknown"),
        build_channel=str(payload.get("build_channel") or "unknown"),
        packaged=frozen,
        executable_path=str(executable),
        source_sha256=str(payload.get("source_sha256") or "unknown"),
        source_file_count=int(payload.get("source_file_count") or 0),
    )


BUILD_ROUND_ID = "P9A-R7"


def user_data_root() -> Path:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "2ByteASR"


def build_id_text(identity: BuildIdentity | None = None) -> str:
    build = identity or load_build_identity()
    stamp = str(build.build_time or "unknown").replace("T", " ").replace("Z", " UTC")
    git = str(build.git_sha or "unknown")
    short = git[:7] if git not in {"", "unknown"} else "unknown"
    dirty = "+" if build.git_dirty else ""
    return f"{BUILD_ROUND_ID} {stamp} git {short}{dirty}"


def launch_identity_payload(identity: BuildIdentity | None = None) -> dict[str, object]:
    build = identity or load_build_identity()
    payload = build.to_dict()
    payload.update(
        {
            "build_id": build_id_text(build),
            "round_id": BUILD_ROUND_ID,
            "sys_executable": str(Path(sys.executable).resolve()),
            "sys_argv0": str(sys.argv[0] if sys.argv else ""),
            "sys_frozen": bool(getattr(sys, "frozen", False)),
            "cwd": str(Path.cwd()),
            "app_root": str(Path(__file__).resolve().parents[1]),
            "resource_root": str(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])),
            "git_commit": build.git_sha,
            "build_timestamp": build.build_time,
        }
    )
    return payload


def write_launch_identity(identity: BuildIdentity | None = None) -> Path:
    payload = launch_identity_payload(identity)
    destination = user_data_root() / "logs" / "build_identity.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def about_build_text(identity: BuildIdentity | None = None) -> str:
    build = identity or load_build_identity()
    lines = [
        f"Build ID: {build_id_text(build)}",
        f"Version: {build.app_version}",
        f"Git SHA: {build.git_sha}",
        f"Build time: {build.build_time}",
        f"Build channel: {build.build_channel}",
        f"Executable path: {build.executable_path}",
        f"Runtime: {build.mode}",
    ]
    if not build.packaged:
        lines.extend((
            f"Source hash: {build.source_sha256}",
            f"Dirty state: {'dirty' if build.git_dirty else 'clean'}",
        ))
    return "\n".join(lines)


def startup_identity_lines(identity: BuildIdentity, *, model_root: Path, project_root: Path) -> tuple[str, ...]:
    payload = launch_identity_payload(identity)
    return (
        f"PROCESS_ROLE={os.environ.get('TWOBYTEASR_PROCESS_ROLE', 'main-gui')}",
        f"PID={os.getpid()}",
        f"PARENT_PID={os.getppid()}",
        f"BUILD_ID={payload['build_id']}",
        f"SYS_EXECUTABLE={payload['sys_executable']}",
        f"SYS_ARGV0={payload['sys_argv0']}",
        f"SYS_FROZEN={payload['sys_frozen']}",
        f"CWD={payload['cwd']}",
        f"APP_ROOT={payload['app_root']}",
        f"RESOURCE_ROOT={payload['resource_root']}",
        f"APP_VERSION={identity.app_version}",
        f"GIT_SHA={identity.git_sha}",
        f"GIT_DIRTY={identity.git_dirty}",
        f"SOURCE_SHA256={identity.source_sha256}",
        f"SOURCE_FILE_COUNT={identity.source_file_count}",
        f"BUILD_TIME={identity.build_time}",
        f"BUILD_CHANNEL={identity.build_channel}",
        f"PACKAGED={identity.packaged}",
        f"EXECUTABLE_PATH={identity.executable_path}",
        f"MODEL_ROOT={Path(model_root)}",
        f"PROJECT_ROOT={Path(project_root)}",
    )


def runtime_fingerprint_payload(identity: BuildIdentity | None = None) -> dict[str, object]:
    """Describe the exact runtime modules and P9A feature symbols in use.

    Frozen builds ship the Python sources as data next to the executable, so
    hashing ``module.__file__`` proves which packaged module was imported. In
    a one-file or source-only launch where that file is unavailable, the
    feature-symbol result still records the executable's actual code path.
    """
    build = identity or load_build_identity()
    module_names = (
        "twobyteasr.studio_ui",
        "twobyteasr.studio_mpv",
        "twobyteasr.studio_ai",
        "twobyteasr.visual_design_graph",
        "twobyteasr.playback_clock",
        "twobyteasr.audio_engine",
        "twobyteasr.media_time",
        "twobyteasr.waveform_cache",
        "moss_firered_pipeline",
    )
    module_hashes: dict[str, str] = {}
    module_paths: dict[str, str] = {}
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            module_hashes[module_name] = "unimportable"
            module_paths[module_name] = ""
            continue
        module_path = Path(str(getattr(module, "__file__", "")))
        module_paths[module_name] = str(module_path)
        try:
            module_hashes[module_name] = hashlib.sha256(module_path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            module_hashes[module_name] = "unavailable"

    try:
        visual = importlib.import_module("twobyteasr.visual_design_graph")
        clock = importlib.import_module("twobyteasr.playback_clock")
        mpv = importlib.import_module("twobyteasr.studio_mpv")
        ai = importlib.import_module("twobyteasr.studio_ai")
        settings = importlib.import_module("twobyteasr.settings")
        media_time = importlib.import_module("twobyteasr.media_time")
        waveform = importlib.import_module("twobyteasr.waveform_cache")
        model_pipeline = importlib.import_module("moss_firered_pipeline")
        features = {
            "P9A_R3_MOTION_NORMALIZER_PRESENT": callable(
                getattr(visual, "normalize_motion_graph_to_cue", None)
            ),
            "P9A_R3_EPOCH_SYNC_PRESENT": hasattr(
                getattr(clock, "PlaybackClock", object), "SEEK_ACK_TIMEOUT_MS"
            ) and callable(
                getattr(getattr(mpv, "MpvController", object), "_advance_source_epoch", None)
            ),
            "P9A_R3_TWO_PHASE_ANTIGRAVITY_PRESENT": callable(
                getattr(ai, "_cli_two_phase_generate", None)
            ),
            "P9A_R4_CUE_MOTION_PHASE_PRESENT": callable(
                getattr(visual, "cue_motion_phase", None)
            ),
            "P9A_R4_FIRST_AUDIO_READY_PRESENT": callable(
                getattr(importlib.import_module("twobyteasr.audio_engine"), "_pcm_rms", None)
            ),
            "P9A_R6_CANONICAL_MEDIA_TIME_PRESENT": callable(
                getattr(getattr(media_time, "MediaTimeMapping", object), "describe_seek", None)
            ),
            "P9A_R6_MPV_PRIMARY_AUDIO_PRESENT": "--aid=auto" in mpv.mpv_startup_arguments(
                "mpv.exe", 1, r"\\.\pipe\2byteasr-fingerprint"
            ),
            "STUDIO_SINGLE_AUDIO_SESSION_PRESENT": "--aid=no" in mpv.mpv_startup_arguments(
                "mpv.exe", 1, r"\\.\pipe\2byteasr-fingerprint"
            ) and callable(getattr(importlib.import_module("twobyteasr.audio_engine").StudioAudioEngine, "synchronize_mix", None)),
            "P9A_R6_WAVEFORM_ORIGIN_PRESENT": "sample_timeline_origin_ms" in (
                getattr(getattr(waveform, "WaveformMetadata", object), "__dataclass_fields__", {})
            ),
            "P9A_R6_MODEL_AUDIT_PRESENT": callable(
                getattr(model_pipeline, "_run_audited_model_stage", None)
            ) and callable(getattr(model_pipeline, "_model_stage_summary", None)),
            # Frozen modules may be loaded from the PyInstaller archive, so
            # their ``__file__`` is not a reliable install-root anchor.  The
            # worker scripts are data files and must be visible beside the
            # executable (or in the pyd-free workers directory).
            "P9A_R7_REAL_ASR_WORKERS_PRESENT": any(
                all((root / name).is_file() for name in ("firered_aed_worker.py", "qwen_asr_worker.py"))
                or all((root / "workers" / name).is_file() for name in ("firered_aed_worker.py", "qwen_asr_worker.py"))
                for root in {
                    Path(sys.executable).resolve().parent,
                    Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).resolve().parent).resolve(),
                    Path(getattr(model_pipeline, "__file__", "") or Path(sys.executable)).resolve().parent.parent,
                }
            ),
            "P9A_R7_GPU_UNKNOWN_STATE_PRESENT": callable(
                getattr(importlib.import_module("twobyteasr.hardware"), "collect_gpu_telemetry", None)
            ),
            "P9A_R7_CACHE_ACCEPT_REJECT_PRESENT": callable(
                getattr(importlib.import_module("twobyteasr.cache"), "run_cached_stage", None)
            ),
            "AI_DESIGN_CLI_TIMEOUT_SECONDS": (
                getattr(settings, "DEFAULT_SETTINGS", {}).get("models", {})
                .get("ai_design_cli_timeout_seconds", "unknown")
                if isinstance(getattr(settings, "DEFAULT_SETTINGS", {}), dict)
                else "unknown"
            ),
        }
    except Exception as exc:
        features = {"fingerprint_error": type(exc).__name__}

    return {
        "build": build_id_text(build),
        "source_hash": build.source_sha256,
        "git_sha": build.git_sha,
        "build_time": build.build_time,
        "modules": module_hashes,
        "module_paths": module_paths,
        "features": features,
    }


def runtime_fingerprint_lines(identity: BuildIdentity | None = None) -> tuple[str, ...]:
    payload = runtime_fingerprint_payload(identity)
    modules = payload.get("modules", {})
    features = payload.get("features", {})
    lines = [
        "PACKAGED_RUNTIME_FINGERPRINT",
        f"build: {payload.get('build', '')}",
        f"source_hash: {payload.get('source_hash', '')}",
        f"git_sha: {payload.get('git_sha', '')}",
        f"build_time: {payload.get('build_time', '')}",
    ]
    for module_name in (
        "twobyteasr.studio_ui",
        "twobyteasr.studio_mpv",
        "twobyteasr.studio_ai",
        "twobyteasr.visual_design_graph",
        "twobyteasr.playback_clock",
        "twobyteasr.audio_engine",
        "twobyteasr.media_time",
        "twobyteasr.waveform_cache",
        "moss_firered_pipeline",
    ):
        label = module_name.rsplit(".", 1)[-1] + "_hash"
        lines.append(f"{label}: {modules.get(module_name, '')}")
    for key, value in features.items():
        lines.append(f"{key}: {'yes' if value is True else 'no' if value is False else value}")
    return tuple(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate 2ByteASR build identity metadata")
    parser.add_argument("--write", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--channel", default="")
    args = parser.parse_args(argv)
    payload = write_build_metadata(args.root, args.write, channel=args.channel)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
