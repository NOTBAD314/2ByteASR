"""The plain-string shortcut redacts exactly what every pattern would (2026-10-28)."""
import re

from twobyteasr.diagnostics import event_log
from twobyteasr.diagnostics.event_log import Sanitizer

CORPUS = [
    'PLAYBACK_HEALTH', 'native_publish_fps', 'path-fa7702afd82c78ce.flv', 'd3d11va', '0.064', '-12.5',
    'sk-abcdefghijklmnop', 'sk-proj-ABCDEFGHIJ1234', 'ghp_0123456789abcdef', 'xai-ABCDEFG12345',
    'AIzaSyA1234567890abcdefghij', 'eyJhbGciOiJIUzI1NiJ9abcdefgh', 'ya29.a0AfH6SMBxxxxxxxxxxxx',
    '字幕已生成·部分AI校对未完成', '准备超时；请检查素材和播放器状态。', 'x' * 3000,
    'C:\\Users\\fixture\\a.flv', '/home/user/a.flv', 'https://api.deepseek.com/v1?key=1', 'a@b.cn',
    'api_key=abc123', 'Bearer abc.def', 'token: secret-value', '-' * 5 + 'BEGIN RSA PRIVATE KEY' + '-' * 5 + 'abc',
]


def test_shortcut_matches_the_full_redaction(monkeypatch):
    fast = [Sanitizer(salt=b's' * 32).string(text) for text in CORPUS]
    monkeypatch.setattr(event_log, '_PLAIN', re.compile(r'(?!)'))
    full = [Sanitizer(salt=b's' * 32).string(text) for text in CORPUS]
    assert fast == full
    assert fast[6] == '<credential>' and fast[11] == '<credential>'
    assert len(fast[15]) == 2000


def test_key_cache_keeps_a_session_of_field_names():
    sanitizer = Sanitizer()
    for index in range(1000):
        sanitizer.key(f'field_{index}')
    assert len(sanitizer._key_cache) == 1000
