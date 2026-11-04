"""Require explicit, version-scoped intent before omitting a retained source."""


def require_confirmed_empty_sources(project, cues=None, *, start_ms=None, end_ms=None):
    from .export_issues import ExportPreflightError, export_issues
    issues = export_issues(project, cues, start_ms=start_ms, end_ms=end_ms, validate_structure=False)
    if any(issue.blocking for issue in issues):
        raise ExportPreflightError(issues)
