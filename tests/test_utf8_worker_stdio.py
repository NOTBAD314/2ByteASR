"""Python worker 子进程 stdio 统一 UTF-8 回归（2026-09-20 MOSS 中文乱码）。

根因：worker 以 `python -I`（隔离模式）启动；-I 隐含 -E，无视
PYTHONIOENCODING/PYTHONUTF8 环境变量。ACP=936 的 Windows 上管道子进程
stdout 默认 GBK，父进程按 UTF-8 解码 → 中文全变 U+FFFD。
修复：python_utf8_command() 在解释器后插 `-X utf8`（显式选项，-I 下生效）。
"""
from __future__ import annotations

import subprocess
import sys

from twobyteasr.system.processes import (
    python_utf8_command,
    utf8_worker_environment,
)


SAMPLE = "测试中文：主播说话人识别完成 日本語テスト emoji 🎙️ C:\\Users\\测试用户\\视频.mp4"


def test_python_utf8_command_inserts_flag_after_isolated_mode():
    assert python_utf8_command(["py.exe", "-I", "worker.py", "--x", "1"]) == [
        "py.exe",
        "-I",
        "-X",
        "utf8",
        "worker.py",
        "--x",
        "1",
    ]
    assert python_utf8_command(["py.exe", "worker.py"]) == ["py.exe", "-X", "utf8", "worker.py"]


def test_utf8_worker_environment_sets_pins():
    env = utf8_worker_environment({"PYTHONHOME": "C:/bad", "PATH": "x"})
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert "PYTHONHOME" not in env
    assert env["PATH"] == "x"


def _run_child(args, *, env=None):
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output, _ = process.communicate(timeout=60)
    return output


def test_isolated_worker_speaks_utf8_with_flag():
    """-I + -X utf8 的子进程：中文/日文/emoji/中文路径全链无 U+FFFD。"""
    code = f"print({SAMPLE!r})"
    output = _run_child(python_utf8_command([sys.executable, "-I", "-c", code]))
    assert SAMPLE in output
    assert "\ufffd" not in output


def test_isolated_worker_env_vars_alone_are_ignored():
    """机制回归：-I 下只给环境变量（修复前姿势）钉不住编码。

    只在平台真实回落本地码页时断言（UTF-8 系统上该退化不存在）。
    """
    env = utf8_worker_environment()
    code = "import sys; print(sys.stdout.encoding or '')"
    output = _run_child(
        [sys.executable, "-I", "-c", code],
        env=env,
    ).strip()
    if output.lower().replace("-", "") not in {"utf8", "utf8-sig"}:
        # 本地码页平台（ACP=936 真机）：环境变量姿势必然乱码
        mojibake = _run_child(
            [sys.executable, "-I", "-c", f"print({SAMPLE!r})"],
            env=env,
        )
        assert SAMPLE not in mojibake, (
            "编码回落本地码页却未乱码——请复核测试环境；此断言保护的是"
            "『-I 忽略 PYTHON* 环境变量』这一机制认知"
        )


def test_isolated_worker_reports_utf8_encoding_with_flag():
    code = "import sys; print(sys.stdout.encoding or '')"
    output = _run_child(
        python_utf8_command([sys.executable, "-I", "-c", code])
    ).strip()
    assert output.lower().replace("-", "") in {"utf8", "utf8-sig"}
