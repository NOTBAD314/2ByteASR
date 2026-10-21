"""Read-only, opt-in installed-program probe of synthetic upgrade fixtures."""
from pathlib import Path
import hashlib
import json
import os


def run(manifest):
    boundary = Path(os.environ.get("TWOBYTEASR_TEST_ROOT", "")).resolve()
    manifest = Path(manifest).resolve()
    if not os.environ.get("TWOBYTEASR_TEST_ROOT") or not manifest.is_relative_to(boundary):
        raise ValueError("Upgrade probe requires its own isolated manifest")
    expected = json.loads(manifest.read_text("utf8"))
    def owned(value):
        path = Path(value).resolve()
        if not path.is_relative_to(boundary):
            raise ValueError("Upgrade fixture path escapes test boundary")
        return path
    checks = {}
    from ..projects.studio_project import load_project, project_library_root
    project = load_project(owned(expected["project"]))
    checks["project_loaded_by_installed_production_loader"] = [cue.text for cue in project.cues] == expected["texts"]
    checks["custom_project_library_resolved"] = project_library_root().resolve() == owned(expected["project_root"])
    from ..storage.settings import load_runtime_settings
    settings, _, warnings = load_runtime_settings()
    checks["settings_restored"] = settings["models"]["polish_model"] == "BerLIN" and settings["glossary"]["enable_domain_terms"] is True
    from ..runtime_paths import build_runtime_paths
    paths = build_runtime_paths()
    checks["custom_model_root_resolved"] = paths.model_root.resolve() == owned(expected["model_root"])
    model = owned(expected["model_sentinel"])
    checks["model_reference_and_bytes_intact"] = hashlib.sha256(model.read_bytes()).hexdigest() == expected["model_sha256"]
    from ..system.runtime_registry import resolve_runtime_python
    checks["registered_runtime_reference_resolved"] = Path(resolve_runtime_python("moss", register=False)).resolve() == owned(expected["runtime_python"])
    import subtitle_core as legacy
    from ..glossary.terminology import snapshot_glossaries
    snapshot = snapshot_glossaries(legacy, ["upgrade-fixture"])
    checks["glossary_canonical_case_restored"] = list(snapshot.canonical_terms) == expected["canonical"]
    from ..recognition.recognition_history import parse_recognition_report
    report = parse_recognition_report(owned(expected["report"]))
    checks["recognition_record_readable"] = report.media_name == "isolated-upgrade-fixture" and len(report.payload["segments"]) == 1
    from ..providers.llm_config import read_secret_value
    secret, _ = read_secret_value("POLISH_LLM_API_KEY")
    checks["synthetic_dpapi_credential_readable"] = hashlib.sha256(secret.encode()).hexdigest() == expected["credential_sha256"]
    from PySide6.QtCore import QSettings
    prefs = QSettings("2ByteASR", "2ByteASR")
    checks["qsettings_theme_language_and_user_preference"] = (
        prefs.value("appearance/theme") == "grape" and settings["ui"]["language"] == "ja" and
        prefs.value("upgrade-fixture-custom-preference") == "retained"
    )
    return {"passed": all(checks.values()), "checks": checks, "settings_warnings": warnings,
        "neural_model_load_verified": False, "cli_oauth_login_verified": False,
        "limitations": ["Synthetic model bytes/reference and runtime reference; no neural-model inference",
                        "Synthetic DPAPI credential and inert CLI login sentinel; no real account request"]}
