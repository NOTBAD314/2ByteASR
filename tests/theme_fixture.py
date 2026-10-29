"""Unit-only draft prerequisites for command/selection tests, never pixel evidence.

Real rendering is exercised by test_web_caption_pixels and headed audits.
These fixtures do not represent provider output, visual approval, or user review.
"""
from types import SimpleNamespace
from twobyteasr.caption_design.theme_draft import ThemeDraft,canonical_theme
from twobyteasr.caption_style.style_recipe import StyleRecipe


def bind_ready_draft(page,theme,cue_id):
    drafts=page._theme_drafts()
    cue=next(c for c in page.project.cues if c.id==cue_id)
    drafts.current=ThemeDraft('unit-fixture',page._ai_request_generation,cue_id,cue.text,theme_json=canonical_theme(theme))
    drafts.project=page.project;drafts.phase='READY'
    from twobyteasr.timeline.studio_design_target import DesignTarget
    drafts.target=DesignTarget.capture(page, cue_id)
    drafts.request_project=drafts.target.project_snapshot
    drafts.evidence={'passed':True,'content_hash':drafts.current.content_hash,'unit_fixture':True}
    page._pending_web_theme=SimpleNamespace(cue_id=cue_id,theme=dict(theme),name=theme['name'],
        recipe=StyleRecipe(name=theme['name'],engine='remotion',web_theme=theme))
    drafts.bind_pending()
    return drafts
