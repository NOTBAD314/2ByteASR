"""macOS Keychain credential store, exercised with a fake ``security`` (2026-10-13).

This proves the command contract (no secret on a command line, hex payload,
read-back, not-found, failure fallback). It is not a real-Mac verification.
"""
import json
import sys
from types import SimpleNamespace

import pytest


class FakeSecurity:
    def __init__(self, *, fail_write=False, keychain=True):
        self.items = {}
        self.calls = []
        self.fail_write = fail_write
        self.keychain = keychain

    def __call__(self, argv, input=None, **kw):
        self.calls.append((list(argv), input))
        assert argv[0] == '/usr/bin/security'
        args = argv[1:]
        if args == ['default-keychain']:
            return SimpleNamespace(returncode=0 if self.keychain else 1,
                                   stdout='    "/Users/u/Library/Keychains/login.keychain-db"\n' if self.keychain else '',
                                   stderr='')
        if args == ['-i']:
            if self.fail_write:
                return SimpleNamespace(returncode=0, stdout='', stderr='security: SecKeychainItemCreateFromContent: error')
            parts = input.split()
            assert parts[0] == 'add-generic-password' and '-X' in parts
            service = parts[parts.index('-s') + 1]
            account = parts[parts.index('-a') + 1]
            self.items[(service, account)] = bytes.fromhex(parts[parts.index('-X') + 1]).decode('utf-8')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if args[0] == 'find-generic-password':
            key = (args[args.index('-s') + 1], args[args.index('-a') + 1])
            if key not in self.items:
                return SimpleNamespace(returncode=44, stdout='', stderr='could not be found')
            return SimpleNamespace(returncode=0, stdout=self.items[key] + '\n', stderr='')
        raise AssertionError(args)


def test_keychain_round_trip_never_puts_secret_on_command_line():
    from twobyteasr import macos_keychain
    fake = FakeSecurity()
    assert macos_keychain.available(runner=fake)
    assert macos_keychain.read(runner=fake) is None
    payload = {'schema': 2, 'API__mosi_moss_pro__api.mosi.cn': 'sk-secret-123'}
    macos_keychain.write(payload, runner=fake)
    assert macos_keychain.read(runner=fake) == payload
    for argv, stdin in fake.calls:
        assert 'sk-secret-123' not in ' '.join(argv)
        assert stdin is None or 'sk-secret-123' not in stdin  # hex only


def test_keychain_write_failure_is_reported():
    from twobyteasr import macos_keychain
    with pytest.raises(macos_keychain.KeychainError):
        macos_keychain.write({'schema': 2}, runner=FakeSecurity(fail_write=True))


def test_llm_config_uses_keychain_on_mac_and_falls_back_to_session(monkeypatch, tmp_path):
    from twobyteasr import llm_config, macos_keychain
    fake = FakeSecurity()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(llm_config, '_KEYCHAIN_STATE', {})
    monkeypatch.setattr(macos_keychain, '_run', lambda args, input_text=None, runner=None:
                        fake(['/usr/bin/security', *args], input=input_text))
    monkeypatch.setattr(macos_keychain.os.path, 'exists', lambda path: True)
    monkeypatch.setattr(llm_config, 'secrets_path', lambda: tmp_path / 'secrets.dat')
    llm_config.clear_session_secrets()
    assert llm_config.keychain_storage_enabled() and not llm_config.session_credentials_enabled()
    assert '钥匙串' in llm_config.credential_storage_notice('zh')
    llm_config._write_encrypted_secrets({'schema': 2, 'K': 'v'})
    assert json.loads(fake.items[(macos_keychain.service_name(), macos_keychain.ACCOUNT)]) == {'schema': 2, 'K': 'v'}
    llm_config.clear_session_secrets()
    assert llm_config._read_secrets()['K'] == 'v'
    assert not (tmp_path / 'secrets.dat').exists()  # nothing written to disk on Mac
    # A keychain failure never becomes a plaintext file: session memory only.
    fake.fail_write = True
    llm_config._write_encrypted_secrets({'schema': 2, 'K': 'changed'})
    assert llm_config.session_credentials_enabled()
    assert llm_config._read_secrets()['K'] == 'changed'
    assert not (tmp_path / 'secrets.dat').exists()
    assert '本次会话' in llm_config.credential_storage_notice('zh')
    llm_config.clear_session_secrets()


def test_other_data_roots_never_share_the_daily_keychain_item(monkeypatch, tmp_path):
    from pathlib import Path
    from twobyteasr import macos_keychain
    home = tmp_path / 'home'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    daily = home / 'Library' / 'Application Support'
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(daily))
    assert macos_keychain.service_name() == macos_keychain.SERVICE
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path / 'acceptance'))
    scoped = macos_keychain.service_name()
    assert scoped.startswith(macos_keychain.SERVICE + '.') and scoped != macos_keychain.SERVICE
