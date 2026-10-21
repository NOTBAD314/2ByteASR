"""Real old Setup -> candidate Setup in an owned AUDIT install, no shared data.

Run phases separately so root can serialize installers, builds and GUI audits.
No remote calls, real user data, model downloads or registry association writes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}"
AUDIT_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}-IsolatedAudit_is1"
REAL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf8")


def read(path):
    return json.loads(path.read_text("utf8"))


def registry_tree(path, *, machine=False):
    import winreg
    root = winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER
    def walk(path, view):
        try:
            key = winreg.OpenKey(root, path, 0, winreg.KEY_READ | view)
        except FileNotFoundError:
            return None
        with key:
            values = []
            children = {}
            for i in range(winreg.QueryInfoKey(key)[1]):
                name, value, kind = winreg.EnumValue(key, i)
                values.append([name, list(value) if isinstance(value, bytes) else value, kind])
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                children[name] = walk(path + "\\" + name, view)
            return {"values": sorted(values), "children": children}
    return {name: walk(path, flag) for name, flag in (("64", winreg.KEY_WOW64_64KEY), ("32", winreg.KEY_WOW64_32KEY))}


def protected_registry():
    return {"HKCU": {key: registry_tree(key) for key in (
        REAL_KEY, r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.2byteproj\UserChoice",
        r"Software\Classes\2ByteASR.Project", r"Software\Classes\.2byteproj",
        r"Software\Classes\Applications\2ByteASR.exe")}, "HKLM": registry_tree(REAL_KEY, machine=True)}


def inventory(base):
    return {path.relative_to(base).as_posix(): {"bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(base.rglob("*")) if path.is_file()}


def env_for(out):
    env = os.environ.copy()
    for key in tuple(env):
        if key.endswith(("_API_KEY", "_TOKEN", "_AUTH_TOKEN", "_ACCESS_TOKEN")) or key.startswith("TWOBYTEASR_") or key.startswith("2BYTEASR_"):
            env.pop(key, None)
    profile = out / "profile"
    env.update(TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
        LOCALAPPDATA=str(profile / "local"), APPDATA=str(profile / "roaming"),
        TEMP=str(profile / "temp"), TMP=str(profile / "temp"), USERPROFILE=str(profile / "profile"),
        HOME=str(profile / "profile"), CODEX_HOME=str(profile / "profile" / ".codex"),
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY="1",
        HF_HOME=str(profile / "hf-cache"), MODELSCOPE_CACHE=str(profile / "modelscope-cache"),
        TORCH_HOME=str(profile / "torch-cache"), QT_QPA_PLATFORM="offscreen",
        **{"2BYTEASR_USER_DATA_ROOT": str(profile / "local"), "2BYTEASR_MODEL_ROOT": str(profile / "models")})
    return env


def invoke(out, executable, args, name, *, installed=False, probe=False):
    from isolated_windows_desktop import run_on_desktop
    env = env_for(out)
    if installed:
        env["2BYTEASR_INSTALL_ROOT"] = str(out / "installed custom path" / "兔白字幕")
    if probe:
        env["TWOBYTEASR_UPGRADE_DATA_PROBE"] = str(out / "profile" / "upgrade-fixture.json")
    started = time.monotonic()
    code = run_on_desktop([str(executable), *args], cwd=ROOT, env=env,
        output=out / (name + "-process"), timeout=600)
    result = {"executable": str(executable), "arguments": args, "exit_code": code,
              "seconds": round(time.monotonic() - started, 3)}
    write(out / (name + ".json"), result)
    if code:
        raise RuntimeError(f"{name} failed; preserve audit log; exit {code}")
    if protected_registry() != read(out / "registry-before.json"):
        raise RuntimeError("Protected shared registry changed")
    return result


def seed(out):
    os.environ.update(env_for(out))
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    # Isolation intentionally replaces inherited custom paths. Set this owned
    # custom reference only after install() and again in the frozen probe.
    profile = out / "profile"
    # This root is outside the ordinary per-user <data>/Models default. The
    # historical package's isolator also confines it to TEST_ROOT/models.
    models = profile / "models"
    projects = profile / "custom 项目 library"
    projects.mkdir(parents=True)
    model = models / "upgrade-model-fixture" / "weights.bin"
    model.parent.mkdir(parents=True); model.write_bytes(b"synthetic model reference: upgrade preservation only\x00\x01")
    from twobyteasr.runtime_paths import build_runtime_paths, persist_runtime_paths
    persist_runtime_paths(build_runtime_paths(install_root=out / "installed custom path" / "兔白字幕", model_root=models))
    runtime = profile / "local" / "2ByteASR" / "runtimes" / "fixture-moss"
    (runtime / "Scripts").mkdir(parents=True)
    (runtime / "Scripts" / "python.exe").write_bytes(b"inert isolated interpreter reference; never execute")
    (runtime / "pyvenv.cfg").write_text("home = isolated fixture\n", "utf8")
    from twobyteasr.system.runtime_registry import register_runtime
    register_runtime("moss", str(runtime / "Scripts" / "python.exe"), source="isolated_upgrade_fixture")
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, save_runtime_settings
    import copy
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["models"]["polish_model"] = "BerLIN"
    settings["glossary"]["enable_domain_terms"] = True
    settings["ui"]["language"] = "ja"
    save_runtime_settings(settings)
    from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue, StudioSpeaker,
        SubtitleStyle, save_project, studio_settings_path)
    media = profile / "fixture.wav"
    with wave.open(str(media), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 16000)
    texts = ["BerLIN S0PP Zhe", "S0pp 一个 123 123"]
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=1000, width=320, height=180),
        speakers=[StudioSpeaker("S1")], styles=[SubtitleStyle(id="default", name="test")],
        cues=[StudioCue("A", 0, 500, texts[0], "S1"), StudioCue("B", 500, 1000, texts[1], "S1")])
    path = save_project(project, projects / "保留大小写.2byteproj")
    write(studio_settings_path(), {"project_root": str(projects), "auto_save": False, "custom_preference": "retained"})
    local = profile / "local" / "2ByteASR"
    canonical = ["BerLIN", "S0PP", "Zhe", "S0pp"]
    write(local / "learned_game_terms.json", {"schema_version": 1, "games": {"upgrade-fixture": {
        "id": "upgrade-fixture", "name": "Upgrade fixture", "revision": 1, "terms": [],
        "mappings": [{"from": "alias-" + str(i), "to": value, "confirmed": True, "origin": "手动", "provenance": "user_confirmed"}
                     for i, value in enumerate(canonical)]}}})
    write(local / "community-glossaries" / "cache-sentinel.json", {"revision": "fixture-1", "sentinel": "previous verified cache; retain"})
    write(local / "cache" / "index-sentinel.json", {"fixture": "retain cache index"})
    report = local / "reports" / "isolated-upgrade_字幕任务报告.json"
    write(report, {"schema_version": 1, "started_at": "2026-10-06T00:00:00Z", "status": "success",
        "media": {"name": "isolated-upgrade-fixture", "duration_seconds": 1},
        "result": {"status": "success"}, "segments": [{"text": texts[0], "start": 0, "end": 1}]})
    from twobyteasr.providers.llm_config import save_api_keys
    credential = "synthetic-credential-upgrade-fixture-no-real-account"
    save_api_keys(polish_key=credential)
    (profile / "profile" / ".codex").mkdir(parents=True)
    write(profile / "profile" / ".codex" / "auth.json", {"inert_fixture": True, "sentinel": "no real OAuth"})
    from PySide6.QtCore import QSettings
    prefs = QSettings("2ByteASR", "2ByteASR")
    for key, value in {"appearance/theme": "grape", "upgrade-fixture-custom-preference": "retained"}.items():
        prefs.setValue(key, value)
    prefs.sync()
    write(profile / "upgrade-fixture.json", {"project": str(path), "project_root": str(projects), "texts": texts,
        "model_root": str(models), "model_sentinel": str(model), "model_sha256": digest(model),
        "runtime_python": str(runtime / "Scripts" / "python.exe"), "canonical": canonical, "report": str(report),
        "credential_sha256": hashlib.sha256(credential.encode()).hexdigest()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=["prepare", "install-old", "upgrade", "uninstall"], required=True)
    parser.add_argument("--old-setup", type=Path)
    parser.add_argument("--candidate-setup", type=Path)
    parser.add_argument("--payload", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Upgrade audit output must be below repository tmp")
    installed = out / "installed custom path" / "兔白字幕"
    if args.phase == "prepare":
        if out.exists() or not args.old_setup or not args.old_setup.is_file():
            raise ValueError("Fresh output and genuine local old Setup required")
        if any(registry_tree(AUDIT_KEY).values()):
            raise ValueError("AUDIT uninstall key already belongs to an unknown installation")
        out.mkdir(parents=True)
        write(out / "registry-before.json", protected_registry())
        write(out / "ownership.json", {"output": str(out), "installed": str(installed),
            "old_setup": str(args.old_setup.resolve()), "old_setup_sha256": digest(args.old_setup),
            "audit_key": AUDIT_KEY, "mode": "AUDIT=1 only"})
        seed(out)
        write(out / "profile-before.json", inventory(out / "profile"))
        print(json.dumps({"prepared": str(out), "old_setup_sha256": digest(args.old_setup)}))
        return
    ownership = read(out / "ownership.json")
    if ownership["output"] != str(out) or ownership["installed"] != str(installed):
        raise ValueError("Installation ownership does not match")
    if protected_registry() != read(out / "registry-before.json"):
        raise ValueError("Shared registry has changed; do not install")
    if args.phase == "install-old":
        old = Path(ownership["old_setup"])
        if digest(old) != ownership["old_setup_sha256"] or installed.exists():
            raise ValueError("Old Setup changed or installation exists")
        invoke(out, old, ["/AUDIT=1", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NOICONS", "/TASKS=", "/NORESTART",
            f"/DIR={installed}", f"/LOG={out / 'old-install.log'}"], "old-install")
        for name in ("2byteasr_settings.json", "game_profiles.json", "glossary.txt"):
            path = installed / name
            if name.endswith(".json"):
                payload = read(path)
                if isinstance(payload, dict):
                    payload["_upgrade_test_sentinel"] = "user-authored fixture; keep original bytes"
                else:
                    payload.append({"_upgrade_test_sentinel": "retained"})
                write(path, payload)
            else:
                path.write_bytes(path.read_bytes() + b"\n# BerLIN S0PP Zhe S0pp preserved user glossary\n")
        (installed / "user-note-retain.txt").write_text("owned upgrade fixture; retain\n", "utf8")
        sentinels = {name: inventory(installed)[name] for name in (
            "2byteasr_settings.json", "game_profiles.json", "glossary.txt", "user-note-retain.txt")}
        write(out / "install-sentinels.json", sentinels)
        invoke(out, installed / "2ByteASR.exe", ["--data-roots-inspect", str(out / "old-roots.json")], "old-data-roots", installed=True)
        write(out / "profile-old.json", inventory(out / "profile"))
        if inventory(out / "profile") != read(out / "profile-before.json"):
            raise RuntimeError("Old install/inspection changed fixture bytes")
    elif args.phase == "upgrade":
        if not args.candidate_setup or not args.payload or not args.candidate_setup.is_file():
            raise ValueError("Candidate Setup and exact sealed payload required")
        if not any(registry_tree(AUDIT_KEY).values()):
            raise ValueError("Owned old AUDIT installation is missing")
        write(out / "candidate-identity.json", {"setup": str(args.candidate_setup.resolve()), "sha256": digest(args.candidate_setup),
            "payload": str(args.payload.resolve()), "build": read(args.payload / "2byteasr_build.json")})
        # Omit /DIR to test inheritance of the old custom installation path.
        invoke(out, args.candidate_setup.resolve(), ["/AUDIT=1", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NOICONS", "/TASKS=", "/NORESTART",
            f"/LOG={out / 'upgrade.log'}"], "upgrade")
        before = read(out / "install-sentinels.json")
        actual = inventory(installed)
        expected = inventory(args.payload.resolve())
        mismatches = [key for key, value in expected.items() if actual.get(key) != (before.get(key) or value)]
        extras = sorted(set(actual) - set(expected) - set(before))
        profile_same = inventory(out / "profile") == read(out / "profile-before.json")
        if mismatches or any(not key.startswith("unins000.") for key in extras) or not profile_same:
            write(out / "upgrade-failed-comparison.json", {"mismatches": mismatches, "extras": extras, "profile_unchanged": profile_same})
            raise RuntimeError("Upgrade did not preserve exact payload/fixture data")
        invoke(out, installed / "2ByteASR.exe", ["--data-roots-inspect", str(out / "candidate-roots.json")], "candidate-data-roots", installed=True, probe=True)
        old = read(out / "old-roots.json"); new = read(out / "candidate-roots.json")
        root_keys = ("user_data_root", "model_root", "project_root", "config_root", "cache_root")
        roots_same = all(old["roots"][key] == new["roots"][key] for key in root_keys)
        probe = new.get("upgrade_fixture_probe", {})
        result = {"passed": roots_same and probe.get("passed") is True and inventory(out / "profile") == read(out / "profile-before.json"),
            "old_setup_sha256": ownership["old_setup_sha256"], "candidate": read(out / "candidate-identity.json"),
            "real_old_setup_to_new_setup": True, "custom_install_directory_inherited": installed.is_dir(),
            "payload_files_verified": len(expected), "payload_mismatches": mismatches, "profile_unchanged": profile_same,
            "install_sentinels_unchanged": all(actual.get(key) == value for key, value in before.items()),
            "roots_unchanged": roots_same, "installed_program_probe": probe,
            "real_registry_unchanged": protected_registry() == read(out / "registry-before.json"),
            "macos_upgrade_verified": False, "clean_vm_verified": False, "global_associations_verified": False}
        write(out / "upgrade-result.json", result)
        if not result["passed"]:
            raise RuntimeError("Installed-program data probe failed")
        print(json.dumps({"passed": True, "payload_files": len(expected), "data_checks": len(probe["checks"])}))
    elif args.phase == "uninstall":
        if not read(out / "upgrade-result.json")["passed"]:
            raise ValueError("Do not uninstall before upgrade evidence is complete")
        invoke(out, installed / "unins000.exe", ["/AUDIT=1", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/LOG={out / 'uninstall.log'}"], "uninstall")
        deadline = time.monotonic() + 30
        while (installed / "unins000.exe").exists() and time.monotonic() < deadline:
            time.sleep(.1)
        result = {"passed": inventory(installed) == read(out / "install-sentinels.json") and
            inventory(out / "profile") == read(out / "profile-before.json") and not any(registry_tree(AUDIT_KEY).values()),
            "remaining": inventory(installed), "profile_unchanged": inventory(out / "profile") == read(out / "profile-before.json"),
            "shared_registry_unchanged": protected_registry() == read(out / "registry-before.json")}
        write(out / "uninstall-preservation.json", result)
        if not result["passed"]:
            raise RuntimeError("Uninstall preservation failed")


if __name__ == "__main__":
    main()
