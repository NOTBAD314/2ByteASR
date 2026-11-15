"""Controlled acceptance-only queue: no model or cloud calls."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

class FakeLegacy:
    PIPELINE_BUILD_ID = "test"
    __file__ = __file__
    HF_TOKEN = ""
    RUNTIME_GAME_NAME = ""
    RUNTIME_ENABLE_DOMAIN_TERMS = False
    RUNTIME_DISCOVERED_TERMS = set()
    RUNTIME_OUTPUT_REVIEW_TRACK = False
    RUNTIME_FORCE_REFRESH_API_CACHE = False
    RUNTIME_FORCE_REFRESH_POLISH_CACHE = False
    RUNTIME_FORCE_REFRESH_GROUP_CACHE = False
    RUNTIME_EXPECTED_SPEAKERS = 0
    RUNTIME_CANCELLATION_TOKEN = None

    def __init__(self, root):
        self.root = Path(root)
        self.observer = None
        self.finished_reports = []
        self.local_asr_session_events = []
        self.task_reporting = SimpleNamespace(
            report_paths_for_media=lambda path: (
                str(self.root / f"{Path(path).stem}.json"),
                str(self.root / f"{Path(path).stem}.txt"),
            )
        )

    @staticmethod
    def canonicalize_runtime_game_name(value):
        return str(value).strip()

    @staticmethod
    def run_startup_self_test():
        return {"id": "test", "checks": 1}

    @staticmethod
    def runtime_content_profile_signature():
        return {}

    @staticmethod
    def runtime_settings_snapshot():
        return {}

    @staticmethod
    def cleanup_old_cache():
        return None

    @staticmethod
    def format_elapsed(seconds):
        return f"{seconds:.0f}s"

    def begin_run_event_log(self):
        return str(self.root / "events.jsonl")

    @contextmanager
    def run_event_observer(self, callback):
        self.observer = callback
        try:
            yield callback
        finally:
            self.observer = None

    def record_run_event(self, event, **payload):
        if self.observer:
            self.observer(event, payload)

    def output_paths_for_media(self, media_path):
        stem = Path(media_path).stem
        return str(self.root / f"{stem}.txt"), str(self.root / f"{stem}.srt")

    def finish_media_report(self, status, **result):
        self.finished_reports.append((status, result))
        return "", ""

    def begin_local_asr_session(self):
        self.local_asr_session_events.append("begin")

    def end_local_asr_session(self):
        self.local_asr_session_events.append("end")


class FakePipeline:
    PIPELINE_BUILD_ID = "test"
    __file__ = __file__

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.processed = []
        self.token = None

    def set_cancellation_token(self, token):
        self.token = token

    @staticmethod
    def check_runtime(legacy):
        return None

    @staticmethod
    def precompute_moss_batch_cache(media_paths, legacy):
        return None

    def process_media(self, media_path, file_index, file_total, legacy):
        self.processed.append(media_path)
        if Path(media_path).name in self.failing:
            raise RuntimeError("synthetic failure")
        txt_path, srt_path = legacy.output_paths_for_media(media_path)
        Path(txt_path).write_text("ok", encoding="utf-8")
        Path(srt_path).write_text("ok", encoding="utf-8")
        return txt_path, srt_path, 0.25


