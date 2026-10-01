"""Role-specific atomic environment repair (USER RECOVERY Change Group 1).

Repair Mode rebuilds only the failing Main / MOSS venv from the deployment
lock.  It never treats ``2byteasr.setup-complete`` as health, never mutates a
live venv in place, and only replaces the live directory after a staging
deep preflight succeeds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

from twobyteasr import environment as env_module
from twobyteasr.processes import run_hidden_subprocess

_ROLE_ORDER = ("main", "moss", "firered_llm", "nemotron")
_ROLE_LABELS = {"nemotron": "Nemotron", "main": "Main", "moss": "MOSS", "firered_llm": "FireRed LLM"}
_POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]


class EnvironmentRepairError(RuntimeError):
    """Staging install or swap failed; the live environment must be kept."""


@dataclass
class UserFacingCopy:
    title: str
    subtitle: str
    repair_label: str
    details_label: str
    details: str
    success_message: str


@dataclass
class RepairPlan:
    roles: list
    title: str
    subtitle: str = "当前环境与此版本 2ByteASR 不兼容"
    details: str = ""
    failures: list = field(default_factory=list)


@dataclass
class RepairResult:
    ok: bool
    roles_repaired: list = field(default_factory=list)
    kept_old: bool = True
    success_message: str = ""
    error: str = ""


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_root():
    try:
        from twobyteasr.runtime_paths import detect_install_root

        return str(detect_install_root())
    except Exception:
        return project_root()


def role_paths(role):
    """Live / staging / backup paths for one role.

    An existing live venv next to the project root is repaired in place —
    never re-created elsewhere. When no live directory exists (a packaged
    install, where ``dist`` is rewritten by every build), the registry's
    intended stable root owns the role and repair creates it there. Staging
    and backup stay beside the live directory so the swap is atomic.
    """
    if role not in _ROLE_ORDER:
        raise EnvironmentRepairError(f"未知环境角色：{role}")
    from twobyteasr.runtime_registry import intended_runtime_root

    directory = ".venv-firered-llm" if role == "firered_llm" else f".venv-{role}"
    legacy_live = os.path.join(project_root(), directory)
    live = legacy_live if os.path.isdir(legacy_live) else intended_runtime_root(role)
    staging = live + ".new"
    backup = live + ".old"
    return {
        "live": live,
        "staging": staging,
        "backup": backup,
        "live_python": os.path.join(live, "Scripts", "python.exe") if os.name == 'nt' else os.path.join(live, 'bin', 'python'),
        "staging_python": os.path.join(staging, "Scripts", "python.exe") if os.name == 'nt' else os.path.join(staging, 'bin', 'python'),
    }


def repair_package_specs(role):
    """Exact ``name==version`` list from the deployment lock (never 2.13)."""
    contract = env_module.environments_contract(role)
    specs = []
    for name, version in (contract.get("packages") or {}).items():
        specs.append(f"{name} @ {contract['package_sources'][name]}" if name in contract.get("package_sources",{}) else f"{name}=={version}")
    specs.append(f"torch=={contract['torch']}")
    specs.append(f"torchaudio=={contract['torchaudio']}")
    return specs


def success_message(roles):
    labels = [_ROLE_LABELS[role] for role in _ROLE_ORDER if role in set(roles)]
    if not labels:
        return "运行环境已修复"
    return "/".join(labels) + " 运行环境已修复"


def user_facing_copy(failures):
    """Ordinary-user title/subtitle; versions stay in details only."""
    roles = []
    detail_lines = []
    for item in failures or []:
        role = getattr(item, "role", "") or ""
        if role and role not in roles:
            roles.append(role)
        label = _ROLE_LABELS.get(role, role or "运行环境")
        problems = list(getattr(item, "problems", None) or [])
        if problems:
            detail_lines.append(f"{label}：")
            detail_lines.extend(f"  {problem}" for problem in problems)
        else:
            detail_lines.append(f"{label}：与此版本部署契约不一致")
    return UserFacingCopy(
        title="运行环境需要更新",
        subtitle="当前环境与此版本 2ByteASR 不兼容",
        repair_label="立即修复",
        details_label="查看详情",
        details="\n".join(detail_lines).strip(),
        success_message=success_message(roles),
    )


def _default_preflight(role, *, interpreter=None, use_cache=True, **_kwargs):
    if interpreter:
        return env_module.deep_preflight(
            role, interpreter=interpreter, use_cache=False
        )
    if use_cache:
        return env_module.preflight(role)
    return env_module.deep_preflight(role, use_cache=False)


def diagnose_repair(settings, *, preflight_fn=None, roles=None):
    """Plan a repair from live preflight.  The setup-complete marker is ignored."""
    runner = preflight_fn or _default_preflight
    if roles is None:
        roles = env_module.required_environment_roles(settings)
    failures = []
    for role in roles:
        result = runner(role, interpreter=None, use_cache=True)
        if not result.ok:
            failures.append(result)
    if not failures:
        return None
    copy = user_facing_copy(failures)
    return RepairPlan(
        roles=[item.role for item in failures],
        title=copy.title,
        subtitle=copy.subtitle,
        details=copy.details,
        failures=failures,
    )


def _remove_tree(path):
    if path and os.path.isdir(path):
        shutil.rmtree(path)


def atomic_replace_directory(live_dir, staging_dir, backup_dir=None):
    """Two-phase directory swap with strong rollback.

    - Never mutates the live directory unless the staging venv passes preflight.
    - On any failure, attempts to restore the original live from backup.
    - After success, the backup is removed.
    - Leaves live intact (or restored) so that "原环境已保留" is accurate.
    """
    live = os.path.abspath(live_dir)
    staging = os.path.abspath(staging_dir)
    backup = os.path.abspath(backup_dir or live + ".old")

    if not os.path.isdir(staging):
        raise EnvironmentRepairError(f"修复暂存环境不存在：{staging}")

    # Remove any stale backup from a prior attempt.
    if os.path.exists(backup):
        shutil.rmtree(backup)

    moved_live = False
    swapped = False
    try:
        if os.path.exists(live):
            os.replace(live, backup)
            moved_live = True
        os.replace(staging, live)
        swapped = True
    except Exception:
        # Best-effort rollback: if we moved live away and did not complete the
        # swap, put the backup back so the original environment is preserved.
        try:
            if moved_live and os.path.exists(backup) and not os.path.exists(live):
                os.replace(backup, live)
        except Exception:
            # Last-ditch: if replace fails, try a copy fallback to avoid total loss.
            try:
                if os.path.exists(backup) and not os.path.exists(live):
                    shutil.copytree(backup, live)
            except Exception:
                pass
        # Re-raise to signal failure; caller will report and keep_old semantics.
        raise
    finally:
        # If we successfully swapped, remove the old live backup.
        if swapped and os.path.exists(backup):
            shutil.rmtree(backup, ignore_errors=True)
        # If swap did not complete but a backup exists and live is missing,
        # the except path already tried to restore.  Do a final safety restore.
        if not swapped:
            try:
                if os.path.exists(backup) and not os.path.exists(live):
                    os.replace(backup, live)
            except Exception:
                try:
                    if os.path.exists(backup) and not os.path.exists(live):
                        shutil.copytree(backup, live)
                except Exception:
                    pass

    # Remove any residual staging directory if it still exists (should not after swap).
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)


def _ps_single_quote(s: str) -> str:
    """Escape a string for safe use inside single quotes in a PowerShell -Command string."""
    # Inside PS single quotes, '' is an escaped single quote.
    return "'" + str(s).replace("'", "''") + "'"


def install_role_from_lock(role, staging_path):
    """Create a fresh staging venv and install the lock contract into it.

    Uses -File driver.ps1 (UTF-8) with explicit -Encoding utf8 arguments to
    avoid -Command string mangling on zh-CN consoles. ASCII-only driver avoids
    source encoding issues inside the PS engine when the parent process
    console codepage is GBK.
    """
    if sys.platform == 'darwin':
        from .platform_macos import macos_copy
        raise EnvironmentRepairError(macos_copy(
            '请在模型工坊的 SenseVoice 卡片选择“安装 / 修复独立环境”；软件会自动准备 CPU 运行库，原环境保持。',
            'Use Prepare / Repair on the SenseVoice card in Model Workshop. The app prepares its private CPU runtime and preserves the previous environment.',
            'モデル工房の SenseVoice カードで準備／修復を選択してください。CPU 実行環境はアプリが準備し、既存環境は保持します。'))
    if os.name != "nt":
        raise EnvironmentRepairError(
            "This repair driver requires Windows. For the macOS experiment "
            "prepare the CPU runtime with scripts/macos_prepare_runtime.py; "
            "the existing runtime has not been changed."
        )
    # The driver ships next to the frozen executable (spec datas) and lives
    # in the repo scripts/ directory in source mode. ProjectRoot must point
    # at the root that carries dependencies.lock.json.
    helper = os.path.join(install_root(), "scripts", "repair_environment_driver.ps1")
    if not os.path.isfile(helper):
        helper = os.path.join(project_root(), "scripts", "repair_environment_driver.ps1")
    if not os.path.isfile(helper):
        raise EnvironmentRepairError(f"缺少修复驱动脚本：{helper}")

    args = (
        _POWERSHELL
        + ["-File", helper]
        + ["-Role", role]
        + ["-ProjectRoot", install_root() if os.path.isfile(os.path.join(install_root(), "dependencies.lock.json")) else project_root()]
        + ["-StagingPath", os.path.abspath(staging_path)]
    )

    completed = run_hidden_subprocess(
        args,
        purpose=f"repair {role} environment",
        runner=subprocess.run,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=project_root(),
    )
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    tail_for_log = combined.strip()[-4000:]
    if completed.returncode != 0:
        raise EnvironmentRepairError(f"{role} 修复安装失败：{tail_for_log}")
    final_py = os.path.join(os.path.abspath(staging_path), "Scripts", "python.exe")
    if not os.path.isfile(final_py):
        raise EnvironmentRepairError(
            f"{role} 修复脚本返回成功但未生成解释器：{final_py}\n"
            f"PowerShell 输出（末尾）：\n{tail_for_log}"
        )
    return {"role": role, "staging": staging_path}


def repair_roles(
    roles,
    *,
    install_fn=None,
    preflight_fn=None,
    swap_fn=None,
):
    """Rebuild each listed role in its own staging venv, then swap only on pass."""
    installer = install_fn or install_role_from_lock
    runner = preflight_fn or _default_preflight
    swapper = swap_fn or atomic_replace_directory
    run_warmup = install_fn is None and preflight_fn is None
    env_module.reset_preflight_cache()
    repaired = []
    last_error = ""
    try:
        for role in roles:
            paths = role_paths(role)
            staging = paths["staging"]
            live = paths["live"]
            backup = paths["backup"]
            trace = env_module.runtime_trace(
                role,
                interpreter=paths["live_python"],
                repair_target=staging,
            )
            _safe_print("[runtime-repair] " + __import__("json").dumps(
                trace, ensure_ascii=False, sort_keys=True
            ))
            try:
                installer(role, staging)
            except Exception as exc:
                _remove_tree(staging)
                last_error = str(exc)
                return RepairResult(
                    ok=False,
                    roles_repaired=list(repaired),
                    kept_old=True,
                    error=last_error,
                )

            # Wait for the newly created interpreter and its packages to be fully visible
            # and importable on Windows (FS/AV/editable .pth can be racy). Use a generous
            # retry window with progressive backoff and explicit warm-up imports.
            staging_py = paths["staging_python"]
            check = None
            warmup_imports = (
                "import sys, importlib; "
                "import torch; "
                "import transformers; "
                "import huggingface_hub; "
            )
            if role == "firered_llm":
                source = os.path.join(project_root(), "third_party", "FireRedASR2S")
                warmup_imports += (
                    f"sys.path.insert(0, {source!r}); "
                    "from fireredasr2s.fireredasr2 import FireRedAsr2; "
                )
            for attempt in range(12):  # up to ~15-20s total; first probes are cheap if ready
                env_module.reset_preflight_cache()
                try:
                    if run_warmup and os.path.isfile(staging_py):
                        # Force visibility + basic import before the heavy probe.
                        _ = run_hidden_subprocess(
                            [staging_py, "-c", warmup_imports + "print('warmup-ok')"],
                            purpose=f"warm up repaired {role} environment",
                            runner=subprocess.run,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30,
                            cwd=project_root(),
                        )
                except Exception:
                    pass
                check = runner(role, interpreter=staging_py, use_cache=False)
                if check.ok:
                    break
                # progressive sleep: 0.5,1,1.5,... up to ~6s per step at the end
                time.sleep(0.5 * (attempt + 1))
            if check is None or not check.ok:
                _remove_tree(staging)
                last_error = "；".join((check.problems if check else [])) or f"{role} 暂存环境未通过检查"
                return RepairResult(
                    ok=False,
                    roles_repaired=list(repaired),
                    kept_old=True,
                    error=last_error,
                )
            try:
                swapper(live, staging, backup)
            except Exception as exc:
                # Swap failed: live should have been restored by swapper.
                # Remove the (now-untrusted) staging tree to complete rollback.
                _remove_tree(staging)
                last_error = str(exc)
                return RepairResult(
                    ok=False,
                    roles_repaired=list(repaired),
                    kept_old=True,
                    error=last_error,
                )
            repaired.append(role)
        return RepairResult(
            ok=True,
            roles_repaired=list(repaired),
            kept_old=False,
            success_message=success_message(repaired),
        )
    finally:
        env_module.reset_preflight_cache()


def _load_runtime_settings():
    path = os.path.join(project_root(), "2byteasr_settings.json")
    try:
        import json

        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError):
        pass
    return {"models": {"primary_asr_backend": "moss"}}


def configuration_repair_roles(_settings=None):
    """Roles repaired by the installer/configurator without an explicit role.

    Setup owns the shared Main workbench. Optional model runtimes are installed
    and repaired by the model workshop, where hardware eligibility and the
    user's selected model are visible. In particular, auto-repairing MOSS on a
    machine without NVIDIA can never pass its CUDA health contract.
    """
    return ["main"]


def _safe_print(*parts, **kwargs):
    """Print text safely under any console encoding (e.g. GBK on zh-CN Windows).

    Replaces unencodable characters instead of raising UnicodeEncodeError.
    """
    sep = kwargs.pop("sep", " ")
    end = kwargs.pop("end", "\n")
    file = kwargs.pop("file", sys.stdout)
    text = sep.join(str(p) for p in parts) + end
    try:
        file.write(text)
        file.flush()
    except UnicodeEncodeError:
        enc = getattr(file, "encoding", None) or "utf-8"
        try:
            b = text.encode(enc, errors="replace")
            try:
                file.buffer.write(b)  # type: ignore[attr-defined]
                file.buffer.flush()   # type: ignore[attr-defined]
            except Exception:
                # Last resort: raw bytes to original file if possible
                os.write(getattr(file, "fileno", lambda: 1)(), b)
        except Exception:
            # Give up silently rather than crashing the repair path.
            pass


def main(argv=None):
    """CLI used by Repair Mode (configurator / bootstrap).  Never deletes live on fail."""
    args = list(sys.argv[1:] if argv is None else argv)
    requested = [item for item in args if item in _ROLE_ORDER]
    settings = _load_runtime_settings()
    if requested:
        roles = requested
    else:
        plan = diagnose_repair(settings, roles=configuration_repair_roles(settings))
        if plan is None:
            _safe_print("运行环境检查通过，无需修复。")
            return 0
        roles = list(plan.roles)
        _safe_print(plan.title)
        _safe_print(plan.subtitle)
        if plan.details:
            _safe_print(plan.details)
    _safe_print("正在修复：" + "、".join(roles))
    result = repair_roles(roles)
    if result.ok:
        _safe_print(result.success_message)
        follow = diagnose_repair(settings, roles=roles)
        if follow is not None:
            _safe_print("修复后复查仍未通过：")
            _safe_print(follow.details)
            return 1
        return 0
    _safe_print("修复未完成，原环境已保留。")
    if result.error:
        _safe_print(result.error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
