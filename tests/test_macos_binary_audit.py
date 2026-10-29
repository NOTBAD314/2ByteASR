import plistlib
import struct

import pytest

from scripts.macos_binary_audit import audit_tree, parse_macho, version


def thin(cpu=0x100000C, target=0x0e0000, sdk=0x1a0200, *, legacy=False, links=()):
    commands = [struct.pack('<4I', 0x24, 16, target, sdk) if legacy else
                struct.pack('<6I', 0x32, 24, 1, target, sdk, 0)]
    for value in links:
        value = value.encode() + b'\0'
        size = (24 + len(value) + 7) // 8 * 8
        commands.append(struct.pack('<6I', 0xc, size, 24, 0, 0, 0) + value + bytes(size-24-len(value)))
    body = b''.join(commands)
    return struct.pack('<8I', 0xfeedfacf, cpu, 0, 6, len(commands), len(body), 0, 0) + body


def test_sdk_does_not_raise_deployment_target():
    result = parse_macho(thin())[0]
    assert result['minimum_macos'] == '14.0.0'
    assert result['sdk'] == '26.2.0'
    assert parse_macho(thin(legacy=True))[0]['minimum_macos'] == '14.0.0'


def test_universal_slices_keep_distinct_minimums(tmp_path):
    arm, intel = thin(), thin(cpu=0x1000007, target=0x0f0000)
    data = (struct.pack('>2I', 0xcafebabe, 2) + struct.pack('>5I', 0x100000C, 0, 48, len(arm), 0)
            + struct.pack('>5I', 0x1000007, 0, 48 + len(arm), len(intel), 0) + arm + intel)
    (tmp_path/'native').write_bytes(data)
    assert audit_tree(tmp_path, arch='arm64', target='14.4.1')['passed']
    failure = audit_tree(tmp_path, arch='x86_64', target='14.4.1')
    assert failure['errors'][0]['required'] == '15.0.0'
    assert not failure['execution_verified']


def test_app_declaration_cannot_hide_a_transitive_dependency(tmp_path):
    (tmp_path/'Contents').mkdir()
    (tmp_path/'Contents/Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion':'14.0'}))
    (tmp_path/'native').write_bytes(thin(target=0x0f0709, links=('/opt/homebrew/opt/missing/lib.dylib',)))
    result = audit_tree(tmp_path, arch='arm64', target='14.4.1')
    assert {e['reason'] for e in result['errors']} == {'minimum_macos', 'external_dependency'}
    assert not result['passed']


def test_wrong_architecture_and_missing_target_fail_closed(tmp_path):
    (tmp_path/'intel').write_bytes(thin(cpu=0x1000007))
    (tmp_path/'unversioned').write_bytes(struct.pack('<8I', 0xfeedfacf,0x100000C,0,6,0,0,0,0))
    result = audit_tree(tmp_path, arch='arm64', target='14.4.1')
    assert {e['reason'] for e in result['errors']} == {'missing_architecture','unknown_deployment_target'}


@pytest.mark.parametrize('data', [thin()[:20], thin()[:-1], struct.pack('>2I',0xcafebabe,999)])
def test_truncated_or_corrupt_files_rejected(data):
    with pytest.raises(ValueError):
        parse_macho(data)


def test_versions_compare_numeric_and_preserve_patch():
    assert version('14.10') > version('14.9.9') > version('14.4.1') > version('14.4')
    assert version('14') == version('14.0.0')
    for invalid in ('', '14.beta', '14.-1', '14.4.1.2', '14.４'):
        with pytest.raises(ValueError):
            version(invalid)
