"""A cp950 console must not stop startup (2026-11-22): the 「[流水线版本]」 line
raised UnicodeEncodeError and the user saw 「运行环境不完整」."""
import io
import sys

import quick_start


def test_unencodable_startup_text_is_replaced_not_raised(monkeypatch):
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding='cp950', errors='strict')
    monkeypatch.setattr(sys, 'stdout', console)
    monkeypatch.setattr(sys, 'stderr', io.TextIOWrapper(io.BytesIO(), encoding='cp950', errors='strict'))
    quick_start._tolerant_console()
    print('[流水线版本] 测试')
    console.flush()
    assert '?' in raw.getvalue().decode('cp950')


def test_streams_without_reconfigure_are_left_alone(monkeypatch):
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    quick_start._tolerant_console()
