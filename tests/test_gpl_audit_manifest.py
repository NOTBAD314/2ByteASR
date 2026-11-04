"""An independent release receipt must remain the audit's expected identity."""
import hashlib
import json
import pytest
from twobyteasr.acceptance.gpl_migration_audit import expected_release


def test_identity_comes_from_external_manifest(tmp_path):
    identity = dict(app_version='0.2.6-test.4', build_channel='separate-channel',
                    source_sha256='a' * 64, git_sha='b' * 40)
    path = tmp_path / 'release.json'
    raw = json.dumps(dict(identity=identity)).encode('utf-8-sig')
    path.write_bytes(raw)
    actual, digest = expected_release(path)
    assert actual == identity
    assert digest == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('invalid', [None, '', 4])
def test_missing_or_nontext_identity_cannot_pass(tmp_path, invalid):
    identity = dict(app_version=invalid, build_channel='c', source_sha256='s', git_sha='g')
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(dict(identity=identity)), encoding='utf8')
    with pytest.raises(ValueError, match='incomplete identity'):
        expected_release(path)
