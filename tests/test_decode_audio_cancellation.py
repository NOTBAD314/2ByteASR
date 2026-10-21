"""P1-6 回归测试：ffmpeg 音频解码可取消、可 watchdog 终止。

安全语义：
- 用户取消（CancellationToken）→ 尽快终止 ffmpeg 进程树 → 抛 CancelledError
- 异常卡死（duration-aware stall limit）→ 终止进程树 → 抛明确 RuntimeError
- 正常长素材不因"运行时间长"被误杀（duration-aware 上限，2x 实时余量）
- 取消/失败不产生有效缓存（不写半成品 npy）
"""

import os
import subprocess
import threading
import time

import numpy as np
import pytest

import subtitle_core  # noqa: F401
from twobyteasr.recognition import cache as cache_mod
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.service import CancelledError, CancellationToken

try:  # TDD：stop_process_tree 尚未提取到 processes.py 时暂缓相关用例
    from twobyteasr.system.processes import stop_process_tree
except ImportError:
    stop_process_tree = None

_TREE_SKIP = pytest.mark.skipif(
    stop_process_tree is None, reason="stop_process_tree 尚未提取"
)


class _FakeProcess:
    """可控的假 Popen：hang 模式 communicate 永远 TimeoutExpired。"""

    def __init__(self, returncode=0, stdout=b"\x00\x00\x00\x00" * 8, stderr=b"", hang=False):
        self.returncode = returncode if not hang else None
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.pid = 424242  # 不存在的 PID；taskkill 会快速失败，不影响断言
        self.killed = False
        self.waited = False
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self._hang:
            raise subprocess.TimeoutExpired("ffmpeg", timeout, output=self._stdout, stderr=self._stderr)
        return self._stdout, self._stderr

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class _PopenQueue:
    """预配置队列 + 已创建记录：append 预配置进程，decode 后按 created 索引访问。"""

    def __init__(self):
        self.queue = []
        self.created = []

    def append(self, proc):
        self.queue.append(proc)

    def __getitem__(self, index):
        return self.created[index]


@pytest.fixture
def fake_popen(monkeypatch):
    queue = _PopenQueue()

    def factory(command, **kwargs):
        proc = queue.queue.pop(0) if queue.queue else _FakeProcess()
        queue.created.append(proc)
        return proc

    monkeypatch.setattr(cache_mod.subprocess, "Popen", factory)
    # stop_process_tree 内部的 taskkill 走 subprocess.run（其内部会再调
    # Popen，撞上上面的 factory）；测试中 stub 掉真实进程终止命令。
    monkeypatch.setattr(
        "twobyteasr.system.processes.subprocess.run", lambda *args, **kwargs: None
    )
    return queue


@pytest.fixture
def no_duration(monkeypatch):
    monkeypatch.setattr(cache_mod, "_probe_media_duration", lambda path: 5.0)


def _decode(path="sample.mp4", token=None, stall_limit=None):
    return cache_mod.decode_audio_to_array(path, cancellation_token=token, _stall_limit=stall_limit)


# ---------------------------------------------------------------- Case A/B：正常与错误退出

def test_case_a_normal_fast_exit_returns_audio(no_duration, fake_popen):
    """Case A：ffmpeg 快速正常退出 → 结果与旧行为一致（float32 mono）。"""
    audio = _decode()
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.size == 8  # 32 bytes / 4


def test_case_b_nonzero_exit_raises_with_stderr(no_duration, fake_popen):
    """Case B：非零退出 → RuntimeError 且 stderr 信息可用。"""
    fake_popen.append(_FakeProcess(returncode=1, stderr=b"sample: Invalid data found"))
    with pytest.raises(RuntimeError, match="Invalid data found"):
        _decode()


# ---------------------------------------------------------------- Case C/D：取消

def test_case_c_cancel_terminates_hanging_process(no_duration, fake_popen):
    """Case C：挂起的 ffmpeg + token 取消 → 终止进程 + CancelledError。"""
    proc = _FakeProcess(hang=True)
    fake_popen.append(proc)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        _decode(token=token)
    assert proc.killed or proc.waited, "取消后必须终止并 reap 进程"


def test_case_d_cancel_after_process_exited_is_clean(no_duration, fake_popen):
    """Case D：进程已自然退出后 token 取消 → 无 kill race，正常收尾。"""
    token = CancellationToken()
    audio = _decode(token=token)  # 默认进程不 hang → 直接完成
    assert audio.size == 8
    assert fake_popen[0].killed is False, "进程已退出不应再 kill"


# ---------------------------------------------------------------- Case E/G：watchdog

def test_case_e_stall_limit_terminates_and_raises(no_duration, fake_popen):
    """Case E：stall limit 触发 → 进程终止 + 明确 RuntimeError。"""
    proc = _FakeProcess(hang=True)
    fake_popen.append(proc)
    with pytest.raises(RuntimeError, match="长时间无响应"):
        _decode(stall_limit=0.5)
    assert proc.killed or proc.waited


def test_case_g_long_media_is_not_killed_by_fixed_300s(no_duration, fake_popen):
    """Case G：合法长媒体（10 小时）的 duration-aware 上限远大于固定 300 秒。"""
    limit = cache_mod._decode_stall_limit(36000.0)
    assert limit >= 36000 * 0.5, "2x 实时余量"
    assert limit > 300, "不得用固定 300 秒误杀长素材"


def test_decode_stall_limit_floor_and_fallback():
    """stall limit 纯函数：下限、公式、duration 缺失回退。"""
    assert cache_mod._decode_stall_limit(10.0) == cache_mod.MIN_DECODE_TIMEOUT_SECONDS
    assert cache_mod._decode_stall_limit(None) == cache_mod.FALLBACK_DECODE_TIMEOUT_SECONDS
    assert cache_mod._decode_stall_limit(0.0) == cache_mod.FALLBACK_DECODE_TIMEOUT_SECONDS


# ---------------------------------------------------------------- Case H：PIPE 大输出

def test_case_h_large_stdout_is_drained(no_duration, fake_popen):
    """Case H：stdout 数据超过普通 pipe buffer → communicate 循环正确收集。"""
    fake_popen.append(_FakeProcess(stdout=b"\x00\x00\x00\x00" * (1 << 20)))  # 4 MB PCM
    audio = _decode()
    assert audio.size == (1 << 20)
    assert fake_popen[0].communicate_calls >= 1


# ---------------------------------------------------------------- Case I：不写半成品缓存

def test_case_i_cancel_does_not_write_cache(no_duration, fake_popen, tmp_path, monkeypatch):
    """Case I：取消后不产生有效缓存 artifact。"""
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"not-really-media")
    ctx = {"cache_dir": str(tmp_path / "cache"), "identity": {"path": str(media), "size": 1, "mtime_ns": 1}}
    os.makedirs(ctx["cache_dir"])
    fake_popen.append(_FakeProcess(hang=True))
    token = CancellationToken()
    token.cancel()
    runtime = RuntimeContext(cancellation_token=token)
    with activate_runtime_context(runtime):
        with pytest.raises(CancelledError):
            cache_mod.load_shared_audio(str(media), ctx)
    assert not os.path.exists(os.path.join(ctx["cache_dir"], "audio_16k.npy")), "不得写入半成品 npy"
    assert not os.path.exists(os.path.join(ctx["cache_dir"], "audio_meta.json")), "不得写入半成品 metadata"


# ---------------------------------------------------------------- Case J：连续调用互不影响

def test_case_j_cancel_then_normal_run(no_duration, fake_popen):
    """Case J：第一次取消，第二次正常运行 → 互不影响。"""
    fake_popen.append(_FakeProcess(hang=True))
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        _decode(token=token)

    audio = _decode()  # 默认新进程，正常完成
    assert audio.size == 8


# ---------------------------------------------------------------- 红测试：旧实现无取消能力

def test_red_old_implementation_has_no_cancel_path(no_duration, fake_popen):
    """回归：挂起的 ffmpeg 在用户取消后必须快速退出并抛 CancelledError。

    旧实现（subprocess.run 无 token）取消后 decode 仍挂住——该测试带
    硬超时（join 1 秒），不会真的挂住 pytest。
    """
    fake_popen.append(_FakeProcess(hang=True))
    token = CancellationToken()
    outcome = {}

    def run_decode():
        try:
            cache_mod.decode_audio_to_array("sample.mp4", cancellation_token=token)
            outcome["ok"] = True
        except BaseException as exc:
            outcome["exc"] = exc

    thread = threading.Thread(target=run_decode)
    thread.start()
    time.sleep(0.2)
    token.cancel()
    thread.join(timeout=1.0)
    assert not thread.is_alive(), "取消后 decode 必须快速退出（旧实现会永久挂住）"
    assert isinstance(outcome.get("exc"), CancelledError), "取消应抛项目统一 CancelledError"


# ---------------------------------------------------------------- stop_process_tree smoke

@_TREE_SKIP
def test_stop_process_tree_is_idempotent_and_reaps(monkeypatch):
    """进程树终止 helper：已退出的进程再次调用无异常（幂等）。"""
    exited = _FakeProcess(returncode=0)
    stop_process_tree(exited)  # poll 非 None → 直接返回，不 kill
    assert exited.killed is False
