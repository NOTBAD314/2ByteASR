"""Freeze the selected timeline instance without changing canonical cue data."""
from dataclasses import dataclass
import copy

from .studio_edit_sequence import projected_cues, source_cue_id_of


def design_cue(project, cue_id):
    if project is None or not cue_id:
        return None
    return next((cue for cue in projected_cues(project) if cue.id == cue_id), None)


@dataclass
class DesignTarget:
    project: object
    session_generation: int
    cue: object
    project_snapshot: object

    @classmethod
    def capture(cls, page, cue_id=None):
        cue = design_cue(page.project, page.selected_cue_id if cue_id is None else cue_id)
        if cue is None:
            return None
        snapshot = copy.deepcopy(page.project)
        snapshot.cues = copy.deepcopy(projected_cues(page.project))
        snapshot.render_settings['_cue_domain'] = 'timeline'
        return cls(page.project, int(getattr(getattr(page, 'session', None), 'generation', 0)),
                   copy.deepcopy(cue), snapshot)

    def matches(self, page):
        if page.project is not self.project:
            return False
        if int(getattr(getattr(page, 'session', None), 'generation', 0)) != self.session_generation:
            return False
        current = design_cue(page.project, self.cue.id)
        # The complete cue includes text, timing, style and placement. Also fence
        # changes to its referenced style or mapping while preparation is queued.
        return (current == self.cue and page.project.styles == self.project_snapshot.styles
                and page.project.style_recipes == self.project_snapshot.style_recipes
                and page.project.edit_sequence == self.project_snapshot.edit_sequence)

    @property
    def canonical_id(self):
        return source_cue_id_of(self.cue.id)
