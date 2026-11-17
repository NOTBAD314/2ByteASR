"""Protect host integration boundaries introduced by multi-attachment and action history."""
from pathlib import Path
import pytest


def test_attachment_reader_bounds_disk_read_and_handles_utf16(tmp_path, monkeypatch):
    from io import BytesIO
    from twobyteasr.app.bunny_attachments import TEXT_LIMIT, read_text_file
    seen=[]
    class Reader(BytesIO):
        def read(self, size=-1):
            seen.append(size)
            assert 0 < size <= TEXT_LIMIT*4
            return super().read(size)
    monkeypatch.setattr(Path,'open',lambda *a,**k:Reader(('日志\n'*50000).encode('utf-16')))
    text=read_text_file(tmp_path/'log.txt')
    assert seen==[TEXT_LIMIT*4] and text.startswith('日志\n') and '\x00' not in text


def test_secret_arguments_are_also_redacted_from_log_question_and_receipt(tmp_path,monkeypatch):
    from twobyteasr.app import bunny_audit
    monkeypatch.setattr(bunny_audit,'log_path',lambda:tmp_path/'actions.jsonl')
    monkeypatch.setattr(bunny_audit,'_allowed',lambda:True)
    secret='sensitive-value-123'
    bunny_audit.record('ui_set',{'api_key':secret},f'- ui_set(api_key={secret})：成功。',question=f'保存 {secret}')
    assert secret not in (tmp_path/'actions.jsonl').read_text('utf8')
    assert bunny_audit.read()[0]['args']['api_key']=='***'


def test_replay_does_not_read_history_when_memory_is_off(monkeypatch):
    from twobyteasr.app import bunny_audit
    from twobyteasr.app.bunny_tools import run_turn
    monkeypatch.setattr(bunny_audit,'_allowed',lambda:False)
    monkeypatch.setattr(bunny_audit,'read',lambda *a:(_ for _ in ()).throw(AssertionError('history was read')))
    assert '关掉了' in run_turn(None,[('replay_action',{'id':1})],None).receipts[0]


@pytest.mark.parametrize('switch',['read_subtitles','read_diagnostics','remember'])
def test_action_history_never_reads_closed_categories_or_disabled_memory(monkeypatch,switch):
    from twobyteasr.app import bunny_audit,bunny_permissions
    from twobyteasr.app.bunny_tools import run_turn
    monkeypatch.setattr(bunny_audit,'read',lambda *a:(_ for _ in ()).throw(AssertionError('history was read')))
    values=dict(bunny_permissions.DEFAULTS,**{switch:False})
    for name in ('recent_actions','replay_action'):
        receipt=run_turn(None,[(name,{'id':1})],values).receipts[0]
        assert '关掉了' in receipt and '成功' not in receipt
