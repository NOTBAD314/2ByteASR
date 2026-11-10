import copy

import pytest

from twobyteasr.projects.studio_project import StudioMedia,SubtitleProject
from twobyteasr.timeline.studio_media_pool import MediaAssetLookup,add_media_asset


def test_batch_preserves_first_matching_path_or_fingerprint(tmp_path):
    project = SubtitleProject(StudioMedia(''))
    first = add_media_asset(project,tmp_path/'a.mp4',fingerprint='first',materialize_audio=False)
    second = add_media_asset(project,tmp_path/'b.mp4',fingerprint='second',materialize_audio=False)
    lookup = MediaAssetLookup(project.media_pool)
    # A path match before a later fingerprint match wins in the old loop.
    assert add_media_asset(project,tmp_path/'a.mp4',fingerprint='second',lookup=lookup) is first
    assert add_media_asset(project,tmp_path/'c.mp4',fingerprint='second',lookup=lookup) is second
    third = add_media_asset(project,tmp_path/'c.mp4',lookup=lookup,materialize_audio=False)
    assert add_media_asset(project,tmp_path/'c.mp4',lookup=lookup) is third
    assert len(project.media_pool) == 3


def test_same_names_different_paths_and_foreign_lookup(tmp_path):
    project = SubtitleProject(StudioMedia(''))
    lookup = MediaAssetLookup(project.media_pool)
    for index in range(100):
        add_media_asset(project,tmp_path/str(index)/'同名.mp4',lookup=lookup,materialize_audio=False)
    assert len(project.media_pool) == 100
    other = copy.copy(project)
    other.media_pool = list(project.media_pool)
    with pytest.raises(ValueError):
        add_media_asset(other,tmp_path/'x.mp4',lookup=lookup)
