"""Runtime environment preflight (Phase B).

Checks Main / MOSS venvs against the deployment contract in
dependencies.lock.json (the single version source of truth — no version is
hard-coded here; PowerShell uses scripts/environment-lock.ps1, Python uses
this module, both read the same JSON).

Two levels:
- fast preflight: interpreter exists + cached deep result whose lock hash
  matches the current lock.
- deep preflight: run a minimal probe inside each environment's own
  interpreter (subprocess, bounded timeout, process tree terminated on
  timeout) and compare installed versions against the exact contract.

Fingerprint semantics (Phase B: in-memory only — persistent location is a
Phase C concern together with install/portable detection): a cached result
means "this environment passed deep preflight under this lock", never
"this environment can never change".  It is invalidated when the interpreter
path disappears or the environments section hash changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from twobyteasr.processes import (
    popen_hidden_subprocess,
    python_utf8_command,
    sanitized_child_environment,
    stop_process_tree,
)

PROBE_TIMEOUT_SECONDS = 60.0

_ENVIRONMENTS_LOCK_KEY = "environments"


class EnvironmentContractError(RuntimeError):
    """The deployment lock is missing or malformed for a required role."""


class EnvironmentPreflightError(RuntimeError):
    """A required environment failed preflight with a structured summary."""

    def __init__(self, message, problems):
        super().__init__(message)
        self.problems = list(problems)


@dataclass
class PreflightResult:
    role: str
    ok: bool
    interpreter: str = ""
    problems: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


_LOCK = threading.RLock()
_CACHE = {}  # role -> (environments_hash, PreflightResult)
_READY_PROBES = {}  # caller key -> ready child-process probe result


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_root():
    """Program location: frozen exe directory, otherwise the repo root."""
    try:
        from twobyteasr.runtime_paths import detect_install_root

        return str(detect_install_root())
    except Exception:
        return project_root()


def lock_path():
    # dependencies.lock.json ships next to the frozen executable and lives at
    # the repo root in source mode; never derive it from __file__ alone,
    # which resolves into the PyInstaller bundle when frozen.
    candidate = os.path.join(install_root(), "dependencies.lock.json")
    if os.path.isfile(candidate):
        return candidate
    return os.path.join(project_root(), "dependencies.lock.json")


def environments_contract(role, *, lock_file=None):
    """Read the deployment contract for one role from dependencies.lock.json."""
    path = lock_file or lock_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, ValueError) as exc:
        raise EnvironmentContractError(f"依赖清单不可读：{path}（{exc}）") from exc
    environments = payload.get(_ENVIRONMENTS_LOCK_KEY)
    if not isinstance(environments, dict) or role not in environments:
        raise EnvironmentContractError(
            f"依赖清单缺少 {role} 环境契约（environments.{role}）。"
        )
    contract = environments[role]
    for field_name in ("python", "torch", "torchaudio"):
        if not contract.get(field_name):
            raise EnvironmentContractError(
                f"environments.{role} 缺少 {field_name} 版本。"
            )
    packages = contract.get("packages")
    if not isinstance(packages, dict) or not packages.get("transformers") or not packages.get(
        "huggingface_hub"
    ):
        raise EnvironmentContractError(
            f"environments.{role}.packages 缺少 transformers / huggingface_hub 精确版本。"
        )
    # Role-aware hub range:
    # - "moss" (and stacks that need transformers>=5) require huggingface_hub >=1.5,<2.
    # - "main" legitimately uses transformers==4.57.6 which declares huggingface-hub<1.0
    #   (historically 0.36.2). Do NOT force modern hub on main.
    if role == "moss":
        _enforce_hf_hub_range(role, packages.get("huggingface_hub"))
    return contract


def _enforce_hf_hub_range(role, version):
    """Fail fast if the lock contains a huggingface_hub outside [1.5, 2)."""
    if not version:
        raise EnvironmentContractError(
            f"environments.{role}.packages.huggingface_hub 为空。"
        )
    try:
        parts = str(version).split(".")
        major = int(parts[0]) if parts else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        major, minor = 0, 0
    if major < 1 or (major == 1 and minor < 5) or major >= 2:
        raise EnvironmentContractError(
            f"environments.{role}.packages.huggingface_hub={version} 违反约束 >=1.5.0,<2.0。"
            " 仅允许部署契约中的 1.x 版本；严禁回退到 0.36.2 等旧版。"
        )


_HASH_CACHE = {}  # lock path -> ((mtime_ns, size), environments hash)


def environments_hash():
    """Deterministic hash of the environments section (fingerprint validity key).

    Cached per lock-file (mtime_ns, size): fast_preflight runs on every Model
    Workshop refresh and used to re-read and parse the 55 KB lock each time.
    """
    path = lock_path()
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    cached = _HASH_CACHE.get(path)
    if stamp is not None and cached is not None and cached[0] == stamp:
        return cached[1]
    with open(path, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    section = payload.get(_ENVIRONMENTS_LOCK_KEY) or {}
    encoded = json.dumps(section, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if stamp is not None:
        _HASH_CACHE[path] = (stamp, digest)
    return digest


def environment_interpreter(role):
    """Explicit interpreter path for a role (never PATH lookup).

    Resolution goes through the RuntimeEnvironmentRegistry: environment
    override, persisted registry, legacy in-place venvs, then the stable
    per-role root under %LOCALAPPDATA%\\2ByteASR\\runtimes. A packaged exe
    therefore reuses the user's existing healthy venvs instead of expecting
    them inside ``dist``. When nothing exists, the stable/intended root is
    returned so diagnostics and repair target one stable location.
    """
    try:
        from twobyteasr.runtime_registry import (
            intended_runtime_root,
            resolve_runtime_python,
            runtime_python_path,
        )

        resolved = resolve_runtime_python(role)
        if resolved:
            return resolved
        return str(runtime_python_path(Path(intended_runtime_root(role))))
    except Exception:
        venv = {
            "main": ".venv-main",
            "moss": ".venv-moss",
            "firered_llm": ".venv-firered-llm",
        }.get(role, f".venv-{role.replace('_', '-')}")
        return os.path.join(project_root(), venv, 'Scripts', 'python.exe') if os.name == 'nt' else os.path.join(project_root(), venv, 'bin', 'python')


def probe_script_path():
    """environment_probe.py as a standalone file runnable by any role python.

    P8C-R3.1: delegates to the single RuntimeEnvironmentRegistry locator
    (``runtime_probe_path``) shared by MAIN, MOSS and repair. Returns ''
    when the probe cannot be found — callers must refuse to spawn and log.
    """
    try:
        from twobyteasr.runtime_registry import runtime_probe_path

        return runtime_probe_path()
    except Exception:
        for candidate in (
            os.path.join(install_root(), "environment_probe.py"),
            os.path.join(project_root(), "twobyteasr", "environment_probe.py"),
        ):
            if os.path.isfile(candidate):
                return candidate
        return ""


def required_environment_roles(runtime_settings):
    """Roles the current pipeline configuration actually needs.

    Main is always required.  MOSS only when the primary backend uses the
    separate .venv-moss environment (a broken MOSS venv must not block e.g.
    a FireRed-only configuration).
    """
    roles = ["main"]
    if runtime_settings:
        primary = str(
            runtime_settings.get("models", {}).get("primary_asr_backend", "moss")
        )
        if primary == "moss":
            roles.append("moss")
        if primary == "firered_llm" or str(
            runtime_settings.get("models", {}).get("qwen_asr_backend", "off")
        ) == "firered_llm":
            roles.append("firered_llm")
    return roles


def runtime_trace(role, *, interpreter=None, repair_target=""):
    """Stable role mapping used by logs, probes, and repair diagnostics."""
    return {
        "model_id": "firered_llm" if role == "firered_llm" else role,
        "runtime_id": role,
        "python_executable": interpreter or environment_interpreter(role),
        "probe_module": {
            "main": "torch,transformers",
            "moss": "moss_transcribe_diarize",
            "firered_llm": "fireredasr2s.fireredasr2.FireRedAsr2",
        }.get(role, role),
        "repair_target": repair_target,
    }


def _run_probe_process(role, contract, *, interpreter=None):
    """Run the deep probe with a bounded timeout; kill the tree on timeout."""
    python_executable = interpreter or environment_interpreter(role)
    trace = runtime_trace(role, interpreter=python_executable)
    print("[runtime] " + json.dumps(trace, ensure_ascii=False, sort_keys=True))
    if not os.path.isfile(python_executable):
        return PreflightResult(
            role=role,
            ok=False,
            interpreter=python_executable,
            problems=[f"解释器缺失：{python_executable}"],
        )
    payload = {
        "role": role,
        "expected": contract,
        "firered_source_dir": (
            os.path.join(project_root(), "third_party", "FireRedASR2S")
            if role == "firered_llm"
            else ""
        ),
    }
    # The probe runs inside the role's own interpreter as a standalone
    # script (stdlib-only, reads one JSON document from stdin). Pointing an
    # external venv python at the repo/bundle via sys.path does not work in
    # packaged mode, where twobyteasr exists only inside the exe archive.
    probe_script = probe_script_path()
    if not probe_script or not os.path.isfile(probe_script):
        # P8C-R3.1 B3: never spawn into "can't open file". Report the exact
        # locator state instead.
        missing_probe = {
            "role": role,
            "probe_path": probe_script,
            "install_root": install_root(),
            "project_root": project_root(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "parent_executable": sys.executable,
        }
        print("[runtime-probe-missing] " + json.dumps(missing_probe, ensure_ascii=False, sort_keys=True))
        return PreflightResult(
            role=role,
            ok=False,
            interpreter=python_executable,
            problems=[
                f"环境探测脚本缺失：{probe_script or '<未定位到 environment_probe.py>'}"
                "（install_root 与 probe 定位见 runtime-probe-missing 日志）"
            ],
        )
    # -I (isolated): the probe file lives in the frozen install root, whose
    # directory Python would otherwise prepend to sys.path — and that
    # directory is full of the GUI's own python3.10 .pyd files, which a
    # 3.12 role venv then loads with "Module use of python310.dll
    # conflicts". Isolated mode keeps stdlib resolution on the venv base.
    # CWD is pinned to the project/install root for the same reason ('' in
    # sys.path resolves extensions from the CWD). It must never be the
    # external interpreter's Scripts/site-packages tree.
    # -I 隐含 -E、无视 PYTHON* 环境变量：-X utf8 钉住探测子进程 stdio，
    # 防止 ACP=936 机器上中文错误文本按 GBK 落管道、父进程按 UTF-8 误读。
    command = python_utf8_command([python_executable, "-I", probe_script])
    probe_cwd = project_root() if not getattr(sys, "frozen", False) else install_root()
    try:
        process = popen_hidden_subprocess(
            command,
            purpose=f"{role} environment probe",
            process_factory=subprocess.Popen,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=probe_cwd,
            env=sanitized_child_environment(),
        )
        stdout, stderr = process.communicate(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            return PreflightResult(
                role=role,
                ok=False,
                interpreter=python_executable,
                problems=[
                    f"{role} 环境探测进程失败（退出码 {process.returncode}）："
                    + (stderr.decode("utf-8", errors="replace") or "")[-400:]
                ],
            )
        try:
            payload_result = json.loads(stdout.decode("utf-8", errors="replace"))
        except ValueError:
            return PreflightResult(
                role=role,
                ok=False,
                interpreter=python_executable,
                problems=[f"{role} 环境探测输出无法解析。"],
            )
        problems = list(payload_result.get("errors") or [])
        payload_result["runtime_trace"] = trace
        return PreflightResult(
            role=role,
            ok=bool(payload_result.get("ok")),
            interpreter=python_executable,
            problems=problems,
            detail=payload_result,
        )
    except subprocess.TimeoutExpired:
        stop_process_tree(process)
        return PreflightResult(
            role=role,
            ok=False,
            interpreter=python_executable,
            problems=[f"{role} 运行环境检查超时（>{PROBE_TIMEOUT_SECONDS:.0f} 秒），已终止。"],
        )
    finally:
        if "process" in locals() and process.poll() is None:
            stop_process_tree(process)


def _cache_valid(role, current_hash):
    entry = _CACHE.get(role)
    if not entry:
        return False
    cached_hash, _result = entry
    return cached_hash == current_hash


def fast_preflight(role):
    """Cheap check: interpreter exists + cached deep result matches lock hash."""
    current_hash = environments_hash()
    interpreter = environment_interpreter(role)
    if not os.path.isfile(interpreter):
        return PreflightResult(
            role=role,
            ok=False,
            interpreter=interpreter,
            problems=[f"{role} 解释器缺失：{interpreter}"],
        )
    if _cache_valid(role, current_hash):
        return _CACHE[role][1]
    return None  # fast check inconclusive -> deep needed


def preflight_cache_token():
    """Changes whenever a cached deep-preflight result is stored or dropped
    (lets a page skip re-rendering environment status that cannot differ)."""
    with _LOCK:
        return tuple(sorted((role, entry[0], id(entry[1])) for role, entry in _CACHE.items()))


def deep_preflight(role, *, interpreter=None, use_cache=True):
    """Full probe; caches a successful live result keyed by the lock hash.

    ``interpreter`` overrides the live role path (used to verify a staging
    venv).  Staging / override probes are never written into the live cache.
    """
    current_hash = environments_hash()
    if use_cache and interpreter is None and _cache_valid(role, current_hash):
        return _CACHE[role][1]
    contract = environments_contract(role)
    result = _run_probe_process(role, contract, interpreter=interpreter)
    if interpreter is None and use_cache:
        if result.ok:
            with _LOCK:
                _CACHE[role] = (current_hash, result)
        else:
            with _LOCK:
                _CACHE.pop(role, None)
    return result


def preflight(role):
    """Fast first; deep only when the fast path is inconclusive."""
    result = fast_preflight(role)
    if result is not None:
        return result
    return deep_preflight(role)


def preflight_roles(roles):
    """Run preflight for several roles and aggregate the first failure.

    Each uncached deep probe starts the role's own interpreter and imports
    torch (MAIN ~3 s, MOSS ~5 s warm). They are independent processes, so
    probe them concurrently; failures keep the requested role order.
    """
    roles = list(roles)
    if len(roles) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(roles), thread_name_prefix="env-preflight") as pool:
            results = list(pool.map(preflight, roles))
    else:
        results = [preflight(role) for role in roles]
    return [result for result in results if not result.ok]


def human_message(result):
    """Structured user-facing message (no raw traceback)."""
    label = {
        "main": "主运行环境",
        "moss": "MOSS 运行环境",
        "firered_llm": "FireRed LLM 运行环境",
    }.get(
        result.role, result.role
    )
    problems = "；".join(result.problems[:4]) or "未知问题"
    return (
        f"{label}不完整或版本不匹配：{problems}。"
        "可点击“立即修复”自动重建该运行环境，无需手动删除环境或设置变量。"
    )


def ensure_environment_ready(runtime_settings, *, roles=None):
    """Correctness gate for queue entry points.

    Raises EnvironmentPreflightError listing all failing roles.  ``roles``
    defaults to ``required_environment_roles(runtime_settings)``.
    """
    roles = list(roles) if roles is not None else required_environment_roles(
        runtime_settings
    )
    failures = preflight_roles(roles)
    if not failures:
        return
    messages = [human_message(item) for item in failures]
    raise EnvironmentPreflightError("；".join(messages), failures)


def reset_preflight_cache():
    with _LOCK:
        _CACHE.clear()
        _READY_PROBES.clear()


def _stat_identity(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def runtime_identity(interpreter):
    """Identity of an interpreter file and of its site-packages folders.

    Installing, upgrading or removing a package adds or removes entries in
    site-packages, which changes that folder's modification time.
    """
    import glob

    interpreter = os.path.abspath(str(interpreter or ""))
    folder = os.path.dirname(interpreter)
    packages = set()
    for pattern in (("..", "Lib", "site-packages"), ("Lib", "site-packages"),
                    ("..", "lib", "python*", "site-packages")):
        packages.update(glob.glob(os.path.join(folder, *pattern)))
    return (interpreter, _stat_identity(interpreter),
            tuple((os.path.normpath(path), _stat_identity(path)) for path in sorted(packages)))


def reuse_ready_probe(key, probe, is_ready):
    """Run a child-process readiness probe once per app session per ``key``.

    Each such probe starts the model interpreter and imports torch (2-6 s).
    Only ready results are kept, so a failure is probed again next time and a
    repair takes effect at once; callers put interpreter/model/source file
    identities into ``key``, and environment repair or a model download clears
    everything through ``reset_preflight_cache``. Returns ``(result, reused)``.
    """
    import copy

    with _LOCK:
        cached = _READY_PROBES.get(key)
    if cached is not None:
        return copy.deepcopy(cached), True
    result = probe()
    if is_ready(result):
        with _LOCK:
            _READY_PROBES[key] = copy.deepcopy(result)
    return result, False
