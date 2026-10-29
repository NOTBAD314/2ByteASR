"""Local troubleshooting of one recognition task (2026-10-23, user request).

The completion page states *what* happened ("字幕保真检查未通过", "部分AI文字
校对未完成"); this module says *why*, from the task report alone. It matches
the report against the known-problem catalog (``diagnosis_catalog``) and
returns findings: which known problem, how sure, the report lines that show
it, and what the user can do.

Pure and read-only: no Qt, no file or network access, the report is never
changed. The caller passes what only it knows (is a text AI configured right
now, the error text of the finished item). The optional AI analysis
(``diagnosis_prompt``) receives these findings as context; it never replaces
them.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Iterable

from .diagnosis_catalog import ISSUES, KnownIssue

# What a finding means for the user, most urgent first.
#   blocker: the task has no usable subtitles because of it
#   problem: a step failed or fell back; subtitles exist, this part is worse
#   quality: nothing failed, but the result is likely poorer than it can be
#   tip:     a setting or update that would help
SEVERITIES = ("blocker", "problem", "quality", "tip")
SEVERITY_LABELS = {"blocker": "导致失败", "problem": "影响结果", "quality": "影响质量", "tip": "小建议"}
# How sure the match is: certain = the report names it; likely = the
# report's facts fit and nothing else explains them; possible = a guess.
CONFIDENCES = ("certain", "likely", "possible")
CONFIDENCE_LABELS = {"certain": "已确认", "likely": "很可能", "possible": "可能"}


@dataclass(frozen=True)
class DiagnosisInput:
    """Everything the checks may read. ``report`` is the task report JSON."""
    report: dict
    item_error: str = ""
    # None: the caller did not say (history page on another machine's report).
    ai_ready: bool | None = None
    app_version: str = ""


@dataclass(frozen=True)
class Finding:
    issue: KnownIssue
    confidence: str
    # Report facts that show it, as "where: value" lines; not translated.
    evidence: tuple[str, ...] = ()
    # One task-specific sentence (zh template + values), optional.
    specific: str = ""
    specific_args: dict = field(default_factory=dict)
    # Names in specific_args whose values are catalog strings (translated on display).
    translate_args: tuple[str, ...] = ()
    severity_override: str = ""

    @property
    def severity(self) -> str:
        return self.severity_override or self.issue.severity

    @property
    def rule_id(self) -> str:
        return self.issue.id

    def sort_key(self):
        return (SEVERITIES.index(self.severity), CONFIDENCES.index(self.confidence))


@dataclass(frozen=True)
class Diagnosis:
    findings: tuple[Finding, ...]
    facts: "RunFacts"

    @property
    def top(self) -> Finding | None:
        return self.findings[0] if self.findings else None

    def headline(self) -> Finding | None:
        """The finding worth a line on the completion page (not a mere tip)."""
        top = self.top
        return top if top is not None and top.severity != "tip" else None

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(finding.rule_id for finding in self.findings)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def clip(text: Any, limit: int = 160) -> str:
    if isinstance(text, float):
        text = round(text, 3)
    value = re.sub(r"\s+", " ", "" if text is None else str(text)).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


class RunFacts:
    """Normalized facts of one report, computed once and shared by the checks."""

    def __init__(self, data: DiagnosisInput):
        from .recognition_outcome import normalize_recognition_outcome
        report = _dict(data.report)
        self.input = data
        self.report = report
        self.result = _dict(report.get("result"))
        self.outputs = _dict(self.result.get("outputs"))
        self.settings = _dict(report.get("settings"))
        self.models = _dict(self.settings.get("models"))
        self.switches = _dict(self.settings.get("switches"))
        self.profile = _dict(self.settings.get("content_profile"))
        self.media = _dict(report.get("media"))
        self.cache = _dict(report.get("cache"))
        self.events = _rows(report.get("events"))
        self.stages = _rows(report.get("stages"))
        self.review_items = _rows(report.get("review_items"))
        self.polish = _dict(report.get("polishing_summary"))
        self.moss = _dict(report.get("moss_execution"))
        self.status = _text(report.get("status")).lower() or "unknown"
        try:
            self.outcome = normalize_recognition_outcome(report)
        except Exception:  # a damaged report still gets the other checks
            self.outcome = None
        self.event_counts = Counter(_text(row.get("event")) for row in self.events)
        self.review_categories = Counter(_text(row.get("category")) for row in self.review_items)
        self.failed_stages = [row for row in self.stages if row.get("status") == "failed"]
        errors = [_text(self.result.get("error")), _text(data.item_error)]
        errors += [_text(row.get("error")) for row in self.failed_stages]
        errors += [_text(row.get("error")) for row in self.events
                   if _text(row.get("event")).endswith(("failed", "failure", "error")) and row.get("error")]
        self.errors = tuple(dict.fromkeys(error for error in errors if error))
        self.error_text = "\n".join(self.errors)
        self.config_warnings = tuple(_text(item) for item in self.settings.get("config_warnings") or () if _text(item))

    # Event helpers -------------------------------------------------------
    def has_event(self, *names: str) -> bool:
        return any(self.event_counts.get(name) for name in names)

    def events_named(self, *names: str) -> list[dict]:
        return [row for row in self.events if _text(row.get("event")) in names]

    def first_event(self, *names: str) -> dict:
        return next(iter(self.events_named(*names)), {})

    def last_event(self, *names: str) -> dict:
        rows = self.events_named(*names)
        return rows[-1] if rows else {}

    def events_matching(self, pattern: str) -> list[dict]:
        compiled = re.compile(pattern)
        return [row for row in self.events if compiled.search(_text(row.get("event")))]

    def error_matches(self, pattern: str, flags=re.IGNORECASE) -> str:
        """The first error line matching ``pattern`` ('' when none)."""
        compiled = re.compile(pattern, flags)
        for error in self.errors:
            if compiled.search(error):
                return error
        return ""

    def review_matches(self, pattern: str, flags=re.IGNORECASE) -> str:
        """The first review item text (category, detail, message) matching ``pattern``."""
        compiled = re.compile(pattern, flags)
        for row in self.review_items:
            text = " ".join(_text(row.get(key)) for key in ("category", "detail", "message") if row.get(key))
            if compiled.search(text):
                return text
        return ""

    def stage_named(self, *parts: str) -> list[dict]:
        return [row for row in self.stages if any(part in _text(row.get("label")) for part in parts)]

    # Setting helpers -----------------------------------------------------
    @property
    def primary(self) -> str:
        return _text(self.models.get("primary_asr_backend")).lower()

    @property
    def timeline(self) -> str:
        return _text(self.models.get("firered_asr_backend")).lower()

    @property
    def language_event(self) -> dict:
        """``TASK_LANGUAGE``: {language, requested, decided_by, disagrees_with_transcript, kana, han…}."""
        return self.last_event("TASK_LANGUAGE")

    @property
    def language(self) -> str:
        """The spoken language the run settled on ('' when the report predates it)."""
        return _text(self.language_event.get("language")).lower()

    @property
    def cue_count(self) -> int:
        try:
            return int(self.result.get("cue_count") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def audio_seconds(self) -> float:
        for value in (self.result.get("audio_seconds"), self.media.get("audio_seconds")):
            try:
                if value:
                    return float(value)
            except (TypeError, ValueError):
                pass
        return 0.0

    @property
    def failed(self) -> bool:
        core = getattr(self.outcome, "core_status", "")
        return core == "failed" or self.status == "failed"

    @property
    def cancelled(self) -> bool:
        return self.status in {"cancelled", "canceled"}

    def setting_line(self, path: str) -> str:
        node: Any = self.settings
        for part in path.split("."):
            node = _dict(node).get(part)
        return f"settings.{path} = {node!r}"


Check = Callable[[RunFacts], "Finding | Iterable[Finding] | None"]
_CHECKS: list[tuple[str, Check]] = []


def check(issue_id: str):
    """Register a check for one catalog entry (the id must exist)."""
    if issue_id not in ISSUES:
        raise KeyError(f"unknown known-issue id: {issue_id}")

    def register(function: Check) -> Check:
        _CHECKS.append((issue_id, function))
        return function
    return register


def found(issue_id: str, confidence: str = "likely", evidence: Iterable[str] = (), *,
          specific: str = "", severity: str = "", translate: Iterable[str] = (), **specific_args) -> Finding:
    if confidence not in CONFIDENCES:
        raise ValueError(confidence)
    if severity and severity not in SEVERITIES:
        raise ValueError(severity)
    return Finding(ISSUES[issue_id], confidence, tuple(clip(line, 240) for line in evidence if line),
                   specific, dict(specific_args), tuple(translate), severity)


def specific_text(finding: Finding, language: str) -> str:
    """The task-specific sentence in ``language`` ('' when the finding has none)."""
    if not finding.specific:
        return ""
    from ..i18n import translate
    values = {key: (translate(str(value), language) if key in finding.translate_args else value)
              for key, value in finding.specific_args.items()}
    return translate(finding.specific, language).format(**values)


def registered_issue_ids() -> tuple[str, ...]:
    _load_checks()
    return tuple(issue_id for issue_id, _check in _CHECKS)


def _load_checks() -> None:
    if not _CHECKS:
        from . import diagnosis_checks  # noqa: F401  (registers on import)


def diagnose_run(data: DiagnosisInput | dict, **kwargs) -> Diagnosis:
    """Run every check; a check that crashes on an odd report is skipped."""
    _load_checks()
    if isinstance(data, dict):
        data = DiagnosisInput(report=data, **kwargs)
    facts = RunFacts(data)
    findings: list[Finding] = []
    for issue_id, function in _CHECKS:
        try:
            result = function(facts)
        except Exception:
            continue
        if result is None:
            continue
        for finding in ((result,) if isinstance(result, Finding) else tuple(result)):
            if finding is not None:
                findings.append(finding)
    # One finding per issue (the most certain one), then a suppression pass:
    # a specific explanation hides its generic sibling.
    best: dict[str, Finding] = {}
    for finding in findings:
        current = best.get(finding.rule_id)
        if current is None or finding.sort_key() < current.sort_key():
            best[finding.rule_id] = finding
    # A failed task always says something: the generic entry when no known
    # problem explains the failure.
    if facts.failed and not any(finding.severity == "blocker" for finding in best.values()):
        best["unknown_failure"] = found("unknown_failure", "possible", [f"result.error = {facts.errors[0]}"] if facts.errors else ())
    hidden = {other for finding in best.values() for other in finding.issue.supersedes}
    ordered = sorted((finding for key, finding in best.items() if key not in hidden),
                     key=lambda finding: (finding.sort_key(), ISSUE_ORDER.get(finding.rule_id, 999)))
    return Diagnosis(tuple(ordered), facts)


ISSUE_ORDER = {issue_id: index for index, issue_id in enumerate(ISSUES)}
