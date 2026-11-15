"""2026-11-15 (user): a newer autosave opens without asking unless 设置 says to ask."""
from __future__ import annotations

import json
from types import SimpleNamespace

from twobyteasr.app.application_settings import effective_recovery_policy


def test_the_newer_autosave_is_the_default():
    assert effective_recovery_policy({}) == 'auto'
    assert effective_recovery_policy(None) == 'auto'
    assert effective_recovery_policy({'recovery_policy': 'nonsense'}) == 'auto'


def test_an_old_stored_ask_was_only_the_old_default():
    assert effective_recovery_policy({'recovery_policy': 'ask'}) == 'auto'
    assert effective_recovery_policy({'recovery_policy': 'ask', 'recovery_policy_chosen': True}) == 'ask'
    assert effective_recovery_policy({'recovery_policy': 'official'}) == 'official'


def test_saving_settings_marks_the_choice_and_other_saves_keep_it(monkeypatch, tmp_path):
    from twobyteasr.app import application_settings as settings
    settings.save_hub_preferences('', True, 60, 9, True, True, 'ask')
    preferences = settings.read_studio_preferences()
    assert preferences['recovery_policy'] == 'ask' and preferences['recovery_policy_chosen'] is True
    assert effective_recovery_policy(preferences) == 'ask'
    settings.save_hub_preferences('', True, 120, 9, True, True)            # not given: kept
    assert effective_recovery_policy(settings.read_studio_preferences()) == 'ask'


def test_opening_uses_the_autosave_without_a_question(tmp_path):
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    from twobyteasr.projects import studio_project_controller as module
    recovered, official = SimpleNamespace(cues=[]), SimpleNamespace()
    calls = []
    controller = SimpleNamespace(page=SimpleNamespace(
        _studio_trace=lambda *a, **k: calls.append(k.get('decision')),
        _studio_preferences=lambda: {'recovery_policy': 'ask'}))   # the old default, never chosen
    candidate = tmp_path / 'p.autosave'
    candidate.write_text('{}', 'utf8')
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(module, 'recoverable_autosave', lambda path, official=None: candidate)
        mp.setattr(module, 'load_project', lambda path: recovered)
        from twobyteasr.projects import studio_project
        mp.setattr(studio_project, 'autosave_fingerprint_sidecar', lambda path: None)
        fingerprints = iter(['official', 'recovered'])
        mp.setattr(studio_project, 'project_content_fingerprint', lambda project: next(fingerprints))
        steps = StudioProjectController._resolve_project_recovery_steps(
            controller, tmp_path / 'p.2byteproj', official, single_shot_fn=lambda *a: None)
        try:
            next(steps)
            raise AssertionError('it asked')
        except StopIteration as done:
            assert done.value == (recovered, True)
    finally:
        mp.undo()
    assert 'auto_recover' in calls
    json.dumps(calls)
