"""Prepare recovery comparisons while the reader exclusively owns the document."""
from dataclasses import dataclass
from pathlib import Path


def recovery_files(path):
    """The checkpoint, overlay and fingerprint all participate in freshness."""
    path=Path(path)
    return (path,path.with_name(path.name+'.overlay'),path.with_name(path.stem+'.fingerprint.json'))


def signature(path):
    rows=[]
    for p in recovery_files(path):
        try:
            st=p.stat();rows.append((str(p.resolve()),st.st_size,st.st_mtime_ns))
        except OSError:
            rows.append((str(p.resolve()),None,None))
    return tuple(rows)


def checkpoint_listing(path,official):
    from .studio_project import autosave_path
    canonical=autosave_path(official,path)
    paths={canonical,*canonical.parent.glob(canonical.stem+'.*.2byteproj')}
    return tuple((str(p.resolve()),signature(p)) for p in sorted(paths) if p.is_file())


@dataclass
class RecoveryInspection:
    project_id: str
    official_path: str
    official_signature: tuple
    candidate: str
    candidate_signature: tuple
    candidates_signature: tuple
    official_fingerprint: str
    equivalent: bool
    recovered: object=None
    invalid: bool=False

    def matches(self,path,official,candidate=None):
        return (self.project_id==official.project_id and self.official_path==str(Path(path).resolve())
            and (candidate is None or self.candidate==str(Path(candidate).resolve()))
            and self.official_signature==signature(path)
            and self.candidate_signature==signature(self.candidate)
            and self.candidates_signature==checkpoint_listing(path,official))


def inspect_recovery(path,official):
    from .studio_project import (ProjectValidationError,autosave_fingerprint_sidecar,
        load_project,project_content_fingerprint,recoverable_autosave)
    candidate=recoverable_autosave(path,official=official)
    if candidate is None:return None
    before,checkpoint=signature(path),signature(candidate)
    listing=checkpoint_listing(path,official)
    fingerprint=project_content_fingerprint(official)
    sidecar=autosave_fingerprint_sidecar(candidate)
    recovered=None;invalid=False
    equivalent=bool(sidecar and str(sidecar.get('content_fingerprint') or '')==fingerprint)
    if not equivalent:
        try:
            recovered=load_project(candidate)
            equivalent=project_content_fingerprint(recovered)==fingerprint
        except (OSError,ProjectValidationError):invalid=True
    return RecoveryInspection(project_id=official.project_id,official_path=str(Path(path).resolve()),
        official_signature=before,candidate=str(candidate.resolve()),candidate_signature=checkpoint,
        candidates_signature=listing,official_fingerprint=fingerprint,equivalent=equivalent,
        recovered=recovered,invalid=invalid)
