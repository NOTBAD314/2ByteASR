"""Exact, small text dependencies; recognition evidence is not a search input."""
from dataclasses import dataclass
import hashlib
import marshal
from ..diagnostics.text_work import count, measured


@measured('text_fingerprint')
def text_key(project, *, mode='both', tracks=None):
    """Also catches legacy writes that emit no revision; excludes view clocks.

    Reading occurs only on the GUI thread. Values passed to a search are
    frozen TextEntry strings and numbers, never the project or Qt widgets.
    """
    meta=project.generation_metadata or {}
    cues=[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id,bool(getattr(c,'locked',False)),
           c.appearance_override.get('translation_group') if mode != 'original' else None) for c in project.cues]
    translated=None
    if mode != 'original':
        container=meta.get('translation_records') or {}
        records=container.get('records') or {}
        translated=(container.get('target'), [(key,r.get('text'),r.get('target')) for key,r in records.items()],
                    meta.get('translations'),meta.get('translation_terminology'),meta.get('translation_glossary'))
    payload=(id(project),project.project_id,mode,tuple(sorted(tracks)) if tracks is not None else None,
        cues,translated,meta.get('language'),meta.get('subtitle_imports'),
        project.studio_state.get('locked_cue_ids'),project.media.path,project.media.fingerprint,
        [(a.asset_id,a.canonical_source,getattr(a,'fingerprint','')) for a in project.media_pool])
    count('text_dependency_scans')
    return hashlib.sha256(marshal.dumps(payload,4)).digest()


@dataclass(frozen=True)
class TextSnapshot:
    key: bytes
    entries: tuple
    mode: str
    tracks: tuple | None

    @property
    def lookup(self):
        return {entry.key:entry for entry in self.entries}
