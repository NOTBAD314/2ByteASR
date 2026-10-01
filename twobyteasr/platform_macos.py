# SPDX-License-Identifier: GPL-3.0-only
"""Explicit native macOS experiment boundary; no Windows data migration."""
from __future__ import annotations
import copy
import os
import platform
import sys
from pathlib import Path
from typing import MutableMapping


def configure_macos_paths(resource_root: Path, *, home: Path | None = None,
                          environ: MutableMapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = (home or Path.home()) / "Library" / "Application Support"
    # Existing USER_DATA_ROOT is a parent-directory contract. It appends the
    # stable 2ByteASR application leaf. Respect explicit isolated roots.
    env.setdefault("2BYTEASR_USER_DATA_ROOT", str(base))
    env.setdefault("LOCALAPPDATA", env["2BYTEASR_USER_DATA_ROOT"])
    env.setdefault("2BYTEASR_INSTALL_ROOT", str(resource_root))
    data = Path(env["2BYTEASR_USER_DATA_ROOT"]) / "2ByteASR"
    # RuntimeRegistry now understands bin/python. Do not turn a discovered
    # old stable runtime into an environment override that masks a repair.
    owned_paths = [resource_root / "tools/ffmpeg/bin", resource_root / "tools/node"]
    env["PATH"] = os.pathsep.join([*(str(p) for p in owned_paths), env.get("PATH", "")])
    return data


def macos_copy(zh: str, en: str, ja: str) -> str:
    from .i18n import current_language
    return {'en': en, 'ja': ja}.get(current_language(), zh)


def cpu_factory_settings(defaults: dict) -> dict:
    settings = copy.deepcopy(defaults)
    settings["models"]["primary_asr_backend"] = "sensevoice"
    switches = settings["switches"]
    for key in ("enable_qwen_asr_reference", "enable_firered_boundary_refinement",
                "enable_ai_polish", "use_ai_grouping", "unified_glm_processing"):
        switches[key] = False
    return settings


def device_capabilities(torch_module=None) -> dict:
    result = {"host_platform": sys.platform, "machine": platform.machine(),
              "cpu": True, "mps_built": False, "mps_available": False,
              "mps_tensor_probe_passed": False, "mps_model_verified": False,
              "selected_asr_device": "cpu"}
    if torch_module is None:
        return result
    try:
        backend = torch_module.backends.mps
        result["mps_built"] = bool(backend.is_built())
        result["mps_available"] = bool(backend.is_available())
        if result["mps_available"]:
            value = torch_module.ones(1, device="mps") + 1
            result["mps_tensor_probe_passed"] = float(value.cpu().item()) == 2.0
    except Exception as exc:
        result["mps_probe_error_type"] = type(exc).__name__
    # Device availability is not a model-support declaration. The existing
    # SenseVoice worker chooses CPU when CUDA is absent; never force MPS.
    return result
