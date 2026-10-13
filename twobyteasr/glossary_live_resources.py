"""Explicit read-only runtime borrowing for the real Home acceptance only.

This hook runs before MainWindow construction. It restores actual existing
interpreters and model paths after test isolation, retaining the ordinary
dependency preflight. It does not change settings, glossaries, jobs or results.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MANIFEST_ENV = 'TWOBYTEASR_LIVE_BORROWED_RESOURCES'
_installed = None


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(path, output):
    """Validate declared existing sources without importing product modules."""
    root = Path(os.environ.get('TWOBYTEASR_INVOKER_CWD') or Path(__file__).resolve().parents[1]).resolve()
    output, path = Path(output).resolve(), Path(path).resolve()
    if not output.is_relative_to(root/'tmp') or not output.is_dir():
        raise ValueError('Real Home acceptance requires an existing owned tmp profile')
    if not path.is_relative_to(root/'tmp') or not path.is_file():
        raise ValueError('Borrowed resources manifest must be an owned repository tmp file')
    manifest = json.loads(path.read_text('utf-8-sig'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Borrowed resources manifest schema_version must be 1')
    protected = {str(path): sha_file(path)}

    def source_file(value, digest, label):
        candidate = Path(value).resolve()
        if not candidate.is_file() or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError('Missing explicitly hashed borrowed source: '+label)
        actual = sha_file(candidate)
        if actual != digest.lower():
            raise ValueError('Borrowed source SHA mismatch: '+label)
        protected[str(candidate)] = actual
        return candidate

    roles = manifest.get('roles')
    if not isinstance(roles, dict) or not {'main', 'moss'} <= set(roles):
        raise ValueError('Existing main and moss roles must be explicitly declared; optional roles are borrowed only when installed')
    resolved_roles = {}
    for role, row in roles.items():
        if role not in ('main', 'moss', 'firered_llm', 'glm_asr', 'canary') or not isinstance(row, dict):
            raise ValueError('Unknown borrowed runtime role')
        python = source_file(row['python'], row['python_sha256'], role+' Python')
        config = source_file(row['venv_config'], row['venv_config_sha256'], role+' pyvenv.cfg')
        if config.name != 'pyvenv.cfg' or not python.is_relative_to(config.parent):
            raise ValueError('Borrowed interpreter must belong to its declared existing venv')
        resolved_roles[role] = str(python)
    model = manifest.get('model_root', {})
    model_root = Path(model.get('path', '')).resolve()
    if not model_root.is_dir() or not model.get('sentinels'):
        raise ValueError('Existing model root and hashed model metadata sentinels are required')
    for row in model['sentinels']:
        sentinel = source_file(row['path'], row['sha256'], 'model metadata sentinel')
        if not sentinel.is_relative_to(model_root):
            raise ValueError('Model metadata sentinel must reside in the borrowed model root')
    secrets = manifest.get('secrets')
    secrets_path = source_file(secrets['path'], secrets['sha256'], 'read-only encrypted secrets') if secrets else None
    cli = manifest.get('grok_home')
    if cli:
        cli_home = Path(cli['path']).resolve()
        source_file(cli_home/'auth.json', cli['auth_sha256'], 'read-only existing CLI auth')
        if cli.get('config_sha256'):
            source_file(cli_home/'config.toml', cli['config_sha256'], 'read-only existing CLI config')
    extra = manifest.get('extra_protected_sources', {})
    if isinstance(extra, dict):
        extra = [dict(path=value, sha256=digest) for value, digest in extra.items()]
    for row in extra:
        source_file(row['path'], row['sha256'], 'additional declared protected source')
    return dict(manifest_path=str(path), manifest=manifest, roles=resolved_roles,
        model_root=str(model_root), secrets_path=secrets_path, protected=protected)


class BorrowedResources:
    def __init__(self, validated, output):
        self.validated, self.output = validated, Path(output).resolve()
        from . import runtime_registry
        from .runtime_paths import MODEL_ROOT_ENV, reset_runtime_paths
        self.original_resolver = runtime_registry.resolve_runtime_python
        self.original_model_root = os.environ.get(MODEL_ROOT_ENV)
        self.original_registry_read_only = os.environ.get('TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY')
        runtime_registry.resolve_runtime_python = lambda role, **kwargs: validated['roles'].get(role, '')
        os.environ['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY'] = '1'
        os.environ[MODEL_ROOT_ENV] = validated['model_root']
        reset_runtime_paths()
        self.original_secret_reader = None
        if validated['secrets_path']:
            from . import llm_config
            self.original_secret_reader = llm_config._read_secrets
            reader = self.original_secret_reader
            llm_config._read_secrets = lambda **kwargs: reader(read_only_path=validated['secrets_path'])
        self.restored = False

    def protection(self):
        rows = []
        for path, digest in self.validated['protected'].items():
            actual = sha_file(path)
            rows.append(dict(path=path, sha256_before=digest, sha256_after=actual, unchanged=actual == digest))
        return rows

    def receipt(self):
        return dict(manifest_path=self.validated['manifest_path'], roles=self.validated['roles'],
            model_root=self.validated['model_root'], secrets_source=str(self.validated['secrets_path'] or ''),
            sources=self.protection(), scope='Existing read-only runtimes/model metadata/encrypted secrets; ordinary preflight retained')

    def restore(self):
        if self.restored:
            return
        from . import runtime_registry
        from .runtime_paths import MODEL_ROOT_ENV, reset_runtime_paths
        runtime_registry.resolve_runtime_python = self.original_resolver
        for key, value in ((MODEL_ROOT_ENV, self.original_model_root),
                           ('TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY', self.original_registry_read_only)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self.original_secret_reader:
            from . import llm_config
            llm_config._read_secrets = self.original_secret_reader
        reset_runtime_paths()
        self.restored = True


def install(output):
    global _installed
    output = Path(output).resolve()
    if (os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') not in {'glossary-live-home', 'perf-recognition', 'ja-bilingual', 'ctc-refine'}
            or Path(os.environ.get('TWOBYTEASR_TEST_ROOT', '')).resolve() != output):
        raise ValueError('Borrowed resources may only be installed in the explicitly isolated real Home acceptance')
    if _installed:
        if _installed.output != output:
            raise ValueError('Borrowed resource hook already belongs to a different acceptance profile')
        if not all(row['unchanged'] for row in _installed.protection()):
            raise ValueError('Borrowed sources changed after installation')
        return _installed
    value = os.environ.get(MANIFEST_ENV, '').strip()
    if not value:
        raise ValueError('An explicit hashed borrowed resources manifest is required for real Home acceptance')
    _installed = BorrowedResources(validate_manifest(value, output), output)
    return _installed
