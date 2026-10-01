"""Minimal environment probe executed by each environment's own interpreter.

Stdlib-only (plus importlib.metadata): the probe must run inside a possibly
broken venv where project dependencies may be missing.  It prints one JSON
object to stdout and never raises into a traceback for expected failures.

Protocol (single JSON object):
{
  "role": "main" | "moss",
  "python_version": "3.10.11",
  "interpreter": "<sys.executable>",
  "packages": {"transformers": "4.57.6", ...}  // None when not installed
  "imports": {"torch": true, "transformers": true, ...}
  "cuda": {"available": true|false|null, "base_version_ok": true|false|null,
           "profile": "cu128" | "unknown"},
  "errors": ["transformers: not installed", ...]
}
"""

from __future__ import annotations

import json
import sys
from importlib import metadata


def _installed_version(package_name):
    try:
        return metadata.version(package_name)
    except Exception:
        return None


def _import_ok(module_name):
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def _import_attr_ok(module_name, attr_path):
    try:
        module = __import__(module_name, fromlist=[attr_path.split(".")[0]])
        for part in attr_path.split("."):
            module = getattr(module, part)
        return True
    except Exception:
        return False


def _strict_cuda_probe(result, runtime_label):
    """Validate the CUDA behavior required by local GPU-only runtimes."""
    try:
        import torch

        cuda_rt = getattr(torch.version, "cuda", None)
        available = bool(torch.cuda.is_available())
        try:
            device_count = int(torch.cuda.device_count())
        except Exception:
            device_count = 0
        result["cuda"]["available"] = available
        result["cuda"]["device_count"] = device_count
        if cuda_rt:
            result["cuda"]["profile"] = (
                "cu128" if "12.8" in str(cuda_rt)
                else "cu126" if "12.6" in str(cuda_rt)
                else str(cuda_rt)
            )
        if not cuda_rt:
            result["errors"].append(
                f"{runtime_label}: torch.version.cuda is None (CPU-only torch installed)"
            )
        if not available:
            result["errors"].append(
                f"{runtime_label}: torch.cuda.is_available() == False"
            )
        if device_count < 1:
            result["errors"].append(f"{runtime_label}: no CUDA devices visible")
        if cuda_rt and available:
            try:
                tensor = torch.zeros(1, device="cuda")
                if not getattr(tensor, "is_cuda", False):
                    result["errors"].append(
                        f"{runtime_label}: CUDA tensor allocation did not land on cuda"
                    )
                else:
                    result["cuda"]["tensor_test_passed"] = True
            except Exception as exc:
                result["errors"].append(
                    f"{runtime_label}: CUDA tensor test failed: {exc}"
                )
    except Exception as exc:
        result["errors"].append(
            f"{runtime_label} gpu validation import/test failed: {exc}"
        )


def run(role, expected, *, project_root=None, firered_source_dir=None):
    """Run the probe for one environment role.

    ``expected`` is the deployment contract read from dependencies.lock.json:
    {"python": "3.10", "torch": "2.11.0", "packages": {...}}.
    """
    result = {
        "role": role,
        "model_id": "firered_llm" if role == "firered_llm" else role,
        "runtime_id": role,
        "python_version": sys.version.split()[0],
        "interpreter": sys.executable,
        "probe_module": {
            "main": "torch,transformers",
            "moss": "moss_transcribe_diarize",
            "firered_llm": "fireredasr2s.fireredasr2.FireRedAsr2",
        }.get(role, role),
        "packages": {},
        "imports": {},
        "cuda": {"available": None, "base_version_ok": None, "profile": "unknown"},
        "errors": [],
    }

    expected_python = str(expected.get("python", "") or "")
    if expected_python and not sys.version.startswith(expected_python + "."):
        result["errors"].append(
            f"python: version {result['python_version']} != contract {expected_python}"
        )

    for name, version in (expected.get("packages") or {}).items():
        installed = _installed_version(name)
        result["packages"][name] = installed
        if installed is None:
            result["errors"].append(f"{name}: not installed")
        elif installed != str(version):
            result["errors"].append(
                f"{name}: version {installed} != contract {version}"
            )

    torch_base = expected.get("torch", "")
    try:
        import torch

        result["imports"]["torch"] = True
        installed_torch = str(torch.__version__ or "")
        result["packages"]["torch"] = installed_torch
        base = installed_torch.split("+")[0]
        if torch_base and base != str(torch_base):
            result["errors"].append(
                f"torch: base version {base} != contract {torch_base}"
            )
            result["cuda"]["base_version_ok"] = False
        else:
            result["cuda"]["base_version_ok"] = True
        available = bool(torch.cuda.is_available())
        result["cuda"]["available"] = available
        if available:
            cuda_version = str(torch.version.cuda or "")
            if "12.6" in cuda_version:
                result["cuda"]["profile"] = "cu126"
            elif "12.8" in cuda_version:
                result["cuda"]["profile"] = "cu128"
    except Exception as exc:
        result["imports"]["torch"] = False
        result["errors"].append(f"torch: import failed ({exc.__class__.__name__})")

    if role == "main":
        result["imports"]["transformers"] = _import_ok("transformers")
        if not result["imports"]["transformers"]:
            result["errors"].append("transformers: import failed")
        result["imports"]["huggingface_hub"] = _import_ok("huggingface_hub")
    elif role == "moss":
        result["imports"]["transformers"] = _import_ok("transformers")
        result["imports"]["auto_model"] = _import_attr_ok(
            "transformers", "AutoModelForCausalLM"
        ) and _import_attr_ok("transformers", "AutoProcessor")
        if not result["imports"]["auto_model"]:
            result["errors"].append(
                "transformers.AutoModelForCausalLM/AutoProcessor: import failed"
            )
        result["imports"]["moss_transcribe"] = _import_ok(
            "moss_transcribe_diarize"
        )
        if not result["imports"]["moss_transcribe"]:
            result["errors"].append("moss_transcribe_diarize: import failed")

        _strict_cuda_probe(result, "moss")
    elif role == 'nemotron':
        result['imports']['nemotron']=all(_import_attr_ok('transformers',name) for name in (
            'AutoProcessor','AutoModelForAudioFrameClassification',
            'Nemotron3DiarizationProcessor','Nemotron3DiarizationForAudioFrameClassification'))
        if not result['imports']['nemotron']:result['errors'].append('Nemotron Transformers classes unavailable')
        try:
            from importlib.metadata import distribution
            direct=json.loads(distribution('transformers').read_text('direct_url.json') or '{}')
            if direct.get('url')!=expected.get('package_sources',{}).get('transformers'):
                result['errors'].append('Transformers source revision does not match Nemotron deployment lock')
        except Exception:
            result['errors'].append('Transformers fixed-source provenance unavailable')
        if not _import_ok('librosa'):result['errors'].append('librosa import failed')
    elif role == "firered_llm":
        if firered_source_dir and firered_source_dir not in sys.path:
            sys.path.insert(0, firered_source_dir)
        result["imports"]["transformers"] = _import_ok("transformers")
        result["imports"]["firered_llm_adapter"] = _import_attr_ok(
            "fireredasr2s.fireredasr2", "FireRedAsr2"
        )
        if not result["imports"]["firered_llm_adapter"]:
            result["errors"].append(
                "fireredasr2s.fireredasr2.FireRedAsr2: import failed"
            )
        _strict_cuda_probe(result, "firered_llm")
    else:
        result["errors"].append(f"unknown runtime role: {role}")

    result["ok"] = not result["errors"]
    return result


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    # Third-party imports may print diagnostics to stdout (including the pinned
    # Transformers snapshot). Keep the one-document probe protocol intact.
    from contextlib import redirect_stdout
    with redirect_stdout(sys.stderr):
        result = run(
            payload.get("role", "main"),
            payload.get("expected", {}),
            firered_source_dir=payload.get("firered_source_dir"),
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
