# SPDX-License-Identifier: GPL-3.0-only
"""Actual path guards; all files and profiles belong to pytest's owned tmp."""
from pathlib import Path
import pytest
from twobyteasr.acceptance.studio_acceptance_audit import audit_directory,audit_tmp_root


@pytest.fixture
def formal_profile(tmp_path,monkeypatch):
    checkout=tmp_path/'source-checkout';checkout.mkdir()
    external=tmp_path/'external-validation';profile=external/'tmp'/'qa-profile'
    output=profile/'normal-gui';output.mkdir(parents=True)
    project=output/'inputs'/'copied.2byteproj';project.parent.mkdir();project.write_text('{}','utf8')
    monkeypatch.chdir(checkout)
    values=dict(TWOBYTEASR_INVOKER_CWD=str(external),TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_ACCEPTANCE_PROFILE_DIR=str(profile),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='unified-studio',TWOBYTEASR_TEST_ROOT=str(profile),
        LOCALAPPDATA=str(profile/'local'),APPDATA=str(profile/'roaming'))
    for key,value in values.items():monkeypatch.setenv(key,value)
    return dict(checkout=checkout,external=external,profile=profile,output=output,project=project)


def test_formal_profile_accepts_explicit_invoker_tmp_and_exact_owned_paths(formal_profile):
    data=formal_profile
    assert audit_tmp_root()==data['external']/'tmp'
    assert not data['output'].is_relative_to(data['checkout']/'tmp')
    assert audit_directory()==data['output']


def test_formal_profile_rejects_real_output_and_copied_project_boundary_escapes(formal_profile,monkeypatch):
    data=formal_profile
    # Both destinations are real directories/files, so failures prove path
    # boundaries rather than accidentally failing a missing-file check.
    cases=(data['external']/'outside-tmp',data['external']/'tmp'/'another-profile')
    for outside in cases:
        outside.mkdir();project=outside/'copied.2byteproj';project.write_text('{}','utf8')
        with monkeypatch.context() as patch:
            patch.setenv('TWOBYTEASR_ACCEPTANCE_DIR',str(outside))
            patch.setenv('TWOBYTEASR_STARTUP_PROJECT',str(project))
            with pytest.raises(ValueError):audit_directory()
    escaped=data['profile']/'other-project.2byteproj';escaped.write_text('{}','utf8')
    with monkeypatch.context() as patch:
        patch.setenv('TWOBYTEASR_STARTUP_PROJECT',str(escaped))
        with pytest.raises(ValueError,match='own copied project'):audit_directory()


def test_formal_profile_rejects_each_mismatched_runtime_or_scenario_binding(formal_profile,monkeypatch):
    data=formal_profile
    mismatches=(('TWOBYTEASR_TEST_ROOT',str(data['profile']/'other')),
        ('LOCALAPPDATA',str(data['profile']/'local'/'nested')),
        ('APPDATA',str(data['profile']/'roaming'/'nested')),
        ('TWOBYTEASR_ACCEPTANCE_PROFILE_DIR',str(data['external']/'tmp'/'other')),
        ('TWOBYTEASR_ACCEPTANCE_SCENARIO','completion-real'))
    for key,value in mismatches:
        with monkeypatch.context() as patch:
            patch.setenv(key,value)
            with pytest.raises(ValueError):audit_directory()


def test_explicit_formal_profile_cannot_bypass_invoker_tmp_or_change_legacy_rules(formal_profile,monkeypatch):
    data=formal_profile
    with monkeypatch.context() as patch:
        patch.setenv('TWOBYTEASR_INVOKER_CWD',str(data['checkout']))
        with pytest.raises(ValueError,match='cwd/tmp'):audit_directory()
    # The established standalone output-local profile still works; an absent
    # opt-in does not enable automatic external-profile discovery.
    legacy=data['checkout']/'tmp'/'legacy';legacy.mkdir(parents=True)
    project=legacy/'copied.2byteproj';project.write_text('{}','utf8')
    with monkeypatch.context() as patch:
        patch.delenv('TWOBYTEASR_ACCEPTANCE_PROFILE_DIR')
        patch.setenv('TWOBYTEASR_INVOKER_CWD',str(data['checkout']))
        patch.setenv('TWOBYTEASR_ACCEPTANCE_DIR',str(legacy))
        patch.setenv('TWOBYTEASR_STARTUP_PROJECT',str(project))
        patch.setenv('LOCALAPPDATA',str(legacy/'local'))
        patch.setenv('APPDATA',str(legacy/'roaming'))
        assert audit_directory()==legacy
        patch.setenv('APPDATA',str(data['profile']/'roaming'))
        with pytest.raises(ValueError,match='isolated app data'):audit_directory()
        patch.delenv('TWOBYTEASR_ACCEPTANCE_DIR')
        assert audit_directory() is None
