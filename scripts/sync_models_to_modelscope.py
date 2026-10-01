r"""Upload local models to a maintainer-owned ModelScope namespace.

The four upstream models already have official ModelScope repositories.  In
normal use only MOSS needs mirroring:

    set MODELSCOPE_API_TOKEN=your_token
    set 2BYTEASR_MODELSCOPE_ORG=your_namespace
    .venv-main\Scripts\python.exe scripts\sync_models_to_modelscope.py --only MOSS-Transcribe-Diarize

Keep the token private.  End users only need the public namespace embedded in
dependencies.lock.json (or supplied through 2BYTEASR_MODELSCOPE_ORG).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

REPOS = {
    "MOSS-Transcribe-Diarize": "MOSS-Transcribe-Diarize",
    "FireRedVAD": "FireRedVAD",
    "FireRedASR2-AED": "FireRedASR2-AED",
    "Qwen3-ASR-1.7B": "Qwen3-ASR-1.7B",
    "spkrec-ecapa-voxceleb": "spkrec-ecapa-voxceleb",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(REPOS),
        metavar="MODEL",
        help="只上传指定模型；可重复使用。默认上传全部本地模型。",
    )
    args = parser.parse_args()

    token = os.environ.get("MODELSCOPE_API_TOKEN", "").strip()
    if not token:
        print("请先设置 MODELSCOPE_API_TOKEN（在 https://modelscope.cn 创建访问令牌）。")
        return 1
    org = os.environ.get("2BYTEASR_MODELSCOPE_ORG", "").strip()
    if not org:
        org = input("ModelScope 个人空间或组织名：").strip()
    if not org:
        print("缺少 ModelScope 空间名。")
        return 1

    selected = args.only or list(REPOS)
    missing = [name for name in selected if not (MODELS / name).is_dir()]
    if missing:
        print(f"本地缺少模型目录：{missing}。请先下载这些模型。")
        return 1

    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "modelscope"],
        check=False,
    )
    if install.returncode != 0:
        print("modelscope SDK 安装失败。")
        return install.returncode
    try:
        from modelscope import HubApi
    except ImportError as exc:
        print(f"无法导入 modelscope SDK：{exc}")
        return 1

    api = HubApi()
    api.login(token)
    for local_name in selected:
        target = f"{org}/{REPOS[local_name]}"
        print(f"[上传] {local_name} -> {target}")
        try:
            api.push_model(model_id=target, local_dir=str(MODELS / local_name))
        except Exception as exc:  # noqa: BLE001 - surface SDK/network failures
            print(f"[失败] {target}：{exc}")
            return 1
        print(f"[完成] {target}")

    print("上传完成。请把下面的公开仓库写入 dependencies.lock.json：")
    for local_name in selected:
        print(f'  "modelscope_repository": "{org}/{REPOS[local_name]}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
