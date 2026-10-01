"""OSS 临时音频中转层（第四十轮）。

Qwen filetrans（录音文件识别）要求**公网可下载**的音频 URL，本地文件无法直接
提交。本层把准备好的 ASR 音频上传到用户自己的阿里云 OSS 临时前缀下，生成
V4 预签名 HTTPS GET URL 交给 Qwen，识别结束后（成功/失败/取消）删除临时对象。

安全约束（用户规格，硬性）：
- 对象 key = ``{prefix}{YYYYMMDD}/{uuid}.{ext}``——绝不把本地文件名当对象标识
  （防碰撞、防文件名泄漏）；
- OSS AccessKey ID/Secret 只在本层做签名，**绝不进入 Qwen 请求体、日志、
  异常文本或 settings 明文**；凭据与 DashScope Key 一样走 Windows DPAPI；
- 预签名 URL 进日志时 query 必须替换为 ``?[REDACTED]``；
- 私有桶设计：不依赖公共读 ACL，下载一律走预签名；
- RAM 子账号最小权限（PutObject/GetObject/DeleteObject）即可使用。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

DEFAULT_OSS_PREFIX = "asr-temp/"
DEFAULT_SIGNED_URL_TTL = 86400
STALE_OBJECT_MAX_AGE_HOURS = 48.0


class OssConfigError(RuntimeError):
    """OSS 临时存储未配置/配置不完整（提示用户到设置里填写）。"""


def redact_signed_url(url: str) -> str:
    """日志安全的预签名 URL：保留对象路径，query 替换为 [REDACTED]。"""
    text = str(url or "")
    if "?" in text:
        head = text.split("?", 1)[0]
        return f"{head}?[REDACTED]"
    return text


@dataclass
class StoredObject:
    key: str
    bucket: str
    region: str
    size_bytes: int
    uploaded_seconds: float


@dataclass
class StorageTestResult:
    ok: bool
    message: str
    object_key: str = ""


class TemporaryAudioStorage(Protocol):
    """临时音频中转抽象。实现负责：上传、预签名、删除、连通性测试、过期清理。"""

    def upload_audio(
        self, payload: bytes, extension: str, *, progress: Callable[[int, int], None] | None = None
    ) -> StoredObject: ...

    def create_download_url(self, key: str, ttl_seconds: int | None = None) -> str: ...

    def verify_download_url(self, url: str) -> None: ...

    def delete_object(self, key: str) -> None: ...

    def test_connection(self) -> StorageTestResult: ...

    def cleanup_stale_objects(self, max_age_hours: float = STALE_OBJECT_MAX_AGE_HOURS) -> int: ...

    def describe(self) -> str: ...


def _normalized_prefix(prefix: str) -> str:
    value = str(prefix or DEFAULT_OSS_PREFIX).strip().lstrip("/")
    if not value:
        return DEFAULT_OSS_PREFIX
    return value if value.endswith("/") else value + "/"


class OssTemporaryStorage:
    """阿里云 OSS 实现：oss2 + AuthV4 签名（V4 预签名 GET URL）。

    ``bucket_impl`` 供测试注入假桶；生产路径懒加载 oss2（模型运行环境可能
    没装该包，但只要不选 filetrans 通道就不应 import 失败）。
    """

    def __init__(
        self,
        *,
        region: str,
        endpoint: str,
        bucket: str,
        prefix: str = DEFAULT_OSS_PREFIX,
        access_key_id: str = "",
        access_key_secret: str = "",
        signed_url_ttl: int = DEFAULT_SIGNED_URL_TTL,
        connect_timeout: int = 30,
        http_get: Callable[..., object] | None = None,
        bucket_impl: object | None = None,
    ):
        self.region = str(region or "").strip()
        self.endpoint = str(endpoint or "").strip()
        self.bucket = str(bucket or "").strip()
        self.prefix = _normalized_prefix(prefix)
        self.access_key_id = str(access_key_id or "").strip()
        self.access_key_secret = str(access_key_secret or "").strip()
        try:
            self.signed_url_ttl = max(60, int(signed_url_ttl or DEFAULT_SIGNED_URL_TTL))
        except (TypeError, ValueError):
            self.signed_url_ttl = DEFAULT_SIGNED_URL_TTL
        self.connect_timeout = int(connect_timeout or 30)
        self._http_get = http_get
        self._bucket_impl = bucket_impl
        if not (self.region and self.endpoint and self.bucket):
            raise OssConfigError(
                "OSS 配置不完整：需要 Region、Endpoint 和 Bucket（设置 → 云端 ASR 中转存储）。"
            )
        if not self.endpoint.lower().startswith("https://"):
            raise OssConfigError("OSS Endpoint 必须使用 https://（预签名 URL 安全要求）。")
        if not (self.access_key_id and self.access_key_secret):
            raise OssConfigError(
                "缺少 OSS AccessKey：请在设置里填写 AccessKey ID / Secret（DPAPI 加密保存）。"
            )

    # ------------------------------------------------------------- 桶访问

    def _bucket(self):
        if self._bucket_impl is not None:
            return self._bucket_impl
        import oss2  # 懒加载：未选 filetrans 通道的环境不需要该依赖

        auth = oss2.AuthV4(self.access_key_id, self.access_key_secret)
        return oss2.Bucket(
            auth,
            self.endpoint,
            self.bucket,
            region=self.region,
            connect_timeout=self.connect_timeout,
        )

    def _new_object_key(self, extension: str) -> str:
        ext = re.sub(r"[^A-Za-z0-9]", "", str(extension or "wav")).lower() or "wav"
        day = datetime.now().strftime("%Y%m%d")
        # 规格硬约束：日期 + uuid，不带本地文件名（防碰撞/防泄漏）。
        return f"{self.prefix}{day}/{uuid.uuid4().hex}.{ext}"

    # ------------------------------------------------------------- 协议方法

    def describe(self) -> str:
        return f"{self.region} · {self.bucket}"

    def upload_audio(
        self, payload: bytes, extension: str, *, progress: Callable[[int, int], None] | None = None
    ) -> StoredObject:
        key = self._new_object_key(extension)
        started = time.perf_counter()
        milestones = {"done": set()}

        def _report(bytes_consumed: int, bytes_total: int):
            if progress is not None:
                try:
                    progress(bytes_consumed, bytes_total)
                except Exception:
                    pass
            total = max(1, int(bytes_total or len(payload)))
            for step in (25, 50, 75):
                if bytes_consumed * 100 >= total * step and step not in milestones["done"]:
                    milestones["done"].add(step)
                    print(f"   [OSS] 上传中 {step}%（{bytes_consumed / 1048576:.1f}/{total / 1048576:.1f} MB）…")

        self._bucket().put_object(key, payload, progress_callback=_report)
        seconds = time.perf_counter() - started
        print(
            f"   [OSS] 上传完成 {key}（{len(payload) / 1048576:.1f} MB，{seconds:.1f}s，"
            f"{self.bucket}/{self.region}）"
        )
        return StoredObject(
            key=key,
            bucket=self.bucket,
            region=self.region,
            size_bytes=len(payload),
            uploaded_seconds=seconds,
        )

    def create_download_url(self, key: str, ttl_seconds: int | None = None) -> str:
        expires = int(ttl_seconds or self.signed_url_ttl)
        url = self._bucket().sign_url("GET", key, expires, slash_safe=True)
        if not str(url).lower().startswith("https://"):
            raise OssConfigError("预签名 URL 不是 https（检查 OSS Endpoint 是否为 https://）。")
        return str(url)

    def verify_download_url(self, url: str) -> None:
        """提交前的最小可达性验证：GET 预签名 URL，读到首字节即断开。"""
        if self._http_get is not None:
            getter = self._http_get
        else:
            import requests

            getter = requests.get
        response = getter(url, timeout=(10, 60), stream=True)
        try:
            status = int(getattr(response, "status_code", 0) or 0)
            if status != 200:
                raise RuntimeError(
                    f"预签名 URL 不可达（HTTP {status}）：请检查 OSS 配置与网络。"
                )
            for _chunk in response.iter_content(1024):
                break
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def delete_object(self, key: str, *, strict=False) -> None:
        try:
            self._bucket().delete_object(key)
        except Exception as exc:
            if strict:raise
            # 删除失败不得打断识别主流程；残留对象由 48h 过期清理兜底。
            print(f"   [OSS][警告] 临时对象删除失败（{key}）：{exc}")

    def test_connection(self) -> StorageTestResult:
        """真实 e2e：上传探针对象 → 预签名 GET 验证 → 删除。"""
        probe_key = ""
        try:
            stored = self.upload_audio(b"2byteasr-oss-probe", "probe")
            probe_key = stored.key
            url = self.create_download_url(stored.key, ttl_seconds=300)
            self.verify_download_url(url)
            self.delete_object(stored.key)
            return StorageTestResult(
                ok=True,
                message=f"OSS 已连接 · {self.describe()}",
                object_key=stored.key,
            )
        except Exception as exc:
            if probe_key:
                self.delete_object(probe_key)
            return StorageTestResult(ok=False, message=f"OSS 连接失败：{exc}")

    # ------------------------------------------------------------- 过期清理

    def _iter_prefix(self, prefix: str):
        import oss2

        return iter(oss2.ObjectIterator(self._bucket(), prefix=prefix, max_keys=1000))

    def cleanup_stale_objects(
        self, max_age_hours: float = STALE_OBJECT_MAX_AGE_HOURS
    ) -> int:
        cutoff = time.time() - float(max_age_hours) * 3600.0
        bucket = self._bucket()
        removed = 0
        for summary in self._iter_prefix(self.prefix):
            try:
                if float(summary.last_modified) < cutoff:
                    bucket.delete_object(summary.key)
                    removed += 1
            except Exception as exc:
                print(f"   [OSS][警告] 过期对象清理跳过 {getattr(summary, 'key', '?')}：{exc}")
        if removed:
            print(f"   [OSS] 过期临时对象清理：删除 {removed} 个（> {max_age_hours:g} 小时）。")
        return removed


def oss_storage_from_settings(
    settings: dict, *, credentials: tuple[str, str] | None = None
) -> OssTemporaryStorage | None:
    """从运行时设置构造 storage；未配置（缺桶或凭据）返回 None。"""
    models = (settings or {}).get("models", {}) or {}
    if not credentials:
        from twobyteasr.llm_config import read_oss_credentials

        credentials = read_oss_credentials()
    key_id, key_secret = credentials
    if not (str(models.get("oss_bucket") or "").strip() and key_id and key_secret):
        return None
    return OssTemporaryStorage(
        region=str(models.get("oss_region") or "cn-hangzhou"),
        endpoint=str(models.get("oss_endpoint") or "https://oss-cn-hangzhou.aliyuncs.com"),
        bucket=str(models.get("oss_bucket") or ""),
        prefix=str(models.get("oss_prefix") or DEFAULT_OSS_PREFIX),
        access_key_id=key_id,
        access_key_secret=key_secret,
        signed_url_ttl=int(models.get("oss_signed_url_ttl") or DEFAULT_SIGNED_URL_TTL),
    )


def cleanup_marker_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    try:
        from twobyteasr.llm_config import secrets_path

        marker = secrets_path().with_name("oss_cleanup_marker.txt")
    except Exception:
        marker = base / "tmp" / "oss_cleanup_marker.txt"
    return marker


def maybe_cleanup_stale_objects(settings: dict) -> int | None:
    """每日一次的过期对象清理入口（启动时调用，全部 best-effort）。

    返回删除数量；今天已清理过 / 未配置 OSS / 任何异常 → None。绝不抛出。
    """
    try:
        marker = cleanup_marker_path()
        today = datetime.now().strftime("%Y-%m-%d")
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == today:
            return None
        storage = oss_storage_from_settings(settings)
        if storage is None:
            return None
        removed = storage.cleanup_stale_objects()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(today, encoding="utf-8")
        return removed
    except Exception as exc:
        print(f"   [OSS][警告] 临时对象日常清理未执行：{exc}")
        return None
