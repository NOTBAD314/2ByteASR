from pathlib import Path
import pytest
from twobyteasr.app.license_documents import resolve_document

def test_viewer_rejects_parent_traversal_and_unrelated_files(tmp_path):
    (tmp_path/'LICENSE').write_text('license')
    (tmp_path/'private.json').write_text('{}')
    assert resolve_document('LICENSE',tmp_path)==tmp_path/'LICENSE'
    for relative in ('../LICENSE','private.json','https://example.com/LICENSE'):
        with pytest.raises(ValueError):resolve_document(relative,tmp_path)

def test_notice_relative_text_is_available_but_archives_are_not_executed(tmp_path):
    folder=tmp_path/'licenses';folder.mkdir()
    (folder/'NOTICE').write_text('notice');(folder/'source.zip').write_bytes(b'PK')
    assert resolve_document('licenses/NOTICE',tmp_path).read_text()=='notice'
    with pytest.raises(ValueError):resolve_document('licenses/source.zip',tmp_path)
