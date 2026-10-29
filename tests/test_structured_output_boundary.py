from collections import UserDict
import json
import threading

import pytest

from twobyteasr.providers.structured_output import object_value, response_object
from twobyteasr.caption_design.web_theme import WebThemeDocument, WebThemeValidationError


@pytest.mark.parametrize('value', [UserDict(answer=1), '{"answer":1}', '```json\n{"answer":1}\n```'])
def test_object_forms(value):
    assert response_object(value) == {'answer': 1}


def test_jsonl_separates_progress_warning_and_final():
    assert response_object('\n'.join(json.dumps(x) for x in [
        {'type': 'progress', 'text': 'private progress'},
        {'type': 'warning', 'text': 'private warning'},
        {'type': 'result', 'result': '{"answer":1}'},
    ])) == {'answer': 1}


@pytest.mark.parametrize('value', [[{'a': 1}], ['private subtitle'], [['one']], 'private subtitle'])
def test_invalid_maps_are_explicit_and_do_not_echo_content(value):
    with pytest.raises(ValueError) as error:
        object_value(value, 'webTheme.appearance')
    assert 'webTheme.appearance' in str(error.value)
    assert 'private subtitle' not in str(error.value)
    assert 'dictionary update sequence' not in str(error.value)


def test_pairs_validate_every_item():
    assert object_value([['a', 1], ['b', 2]], pairs=True) == {'a': 1, 'b': 2}
    for value in [[['a']], ['ab'], [{'a': 1}], [['a', 1], ['a', 2]]]:
        with pytest.raises(ValueError):
            object_value(value, pairs=True)


def test_real_failure_shape_is_reported_before_theme_compilation():
    with pytest.raises(WebThemeValidationError, match=r'webTheme.appearance.*str'):
        WebThemeDocument.from_dict({'appearance': 'private descriptive prose', 'palette': {}})


def test_multiple_terminal_results_are_not_silently_merged():
    with pytest.raises(ValueError, match='one final'):
        response_object('{"type":"result","result":{}}\n{"type":"result","result":{}}')


def test_cancelled_probe_does_not_cancel_next_real_process(monkeypatch, tmp_path):
    import sys
    from twobyteasr.providers.ai_providers import CLIProvider, AIProviderError
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    monkeypatch.setenv('APPDATA', str(tmp_path/'roaming'))
    provider = CLIProvider(executable=sys.executable)
    old = threading.Event(); old.set()
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_command([sys.executable, '-c', 'print(1)'], purpose='models', timeout=3, cancel_check=old.is_set)
    assert error.value.category == 'cancelled'
    new = threading.Event()
    result = provider._run_cli_command([sys.executable, '-c', 'print(2)'], purpose='subtitle generation', timeout=3, cancel_check=new.is_set)
    assert result.stdout.strip() == '2'


def test_independent_operations_and_late_completion():
    from twobyteasr.providers.request_operations import RequestOperations
    registry = RequestOperations()
    old = registry.begin('detect', 1)
    generation = registry.begin('generate', 2)
    login = registry.begin('login', 3)
    old.cancel.set()
    assert not generation.cancel.is_set() and not login.cancel.is_set()
    newer = registry.begin('generate', 4)
    assert generation.cancel.is_set()
    assert registry.finish(2) is generation
    assert registry.current['generate'] is newer and not newer.cancel.is_set()


def test_real_cli_timeout_is_not_user_cancellation(monkeypatch,tmp_path):
    import sys,subprocess
    from twobyteasr.providers.ai_providers import CLIProvider,AIProviderError
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    token=threading.Event();provider=CLIProvider(executable=sys.executable)
    with pytest.raises((subprocess.TimeoutExpired,AIProviderError)) as error:
        provider._run_cli_command([sys.executable,'-c','import time;time.sleep(5)'],purpose='subtitle generation',timeout=.2,cancel_check=token.is_set)
    assert not token.is_set() and getattr(error.value,'category',None)!='cancelled'
