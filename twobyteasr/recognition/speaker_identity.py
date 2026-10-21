"""Speaker identity resolution seam (三十八轮).

MAI diarization returns anonymous, **file-local** speaker IDs (S00/S01/…).
They must never be treated as stable person identities across files or even
across independently transcribed chunks of the same file.  This module is the
reserved abstraction for mapping those local IDs onto durable identities
(speaker embedding / voice profile / manual mapping) without touching the
pipeline contract.

当前实现只有 Passthrough（原样透传，不做任何身份推断——第一版按用户
要求由使用者在 Studio 里人工选一次主讲的 speaker）。
"""

from __future__ import annotations

from typing import Protocol


class SpeakerIdentityResolver(Protocol):
    """Map a file-local diarization speaker id to a stable identity key.

    Contract:
    - ``file_key`` identifies the media/task (path, task id, …) so future
      resolvers can keep per-file embedding caches.
    - ``local_speaker_id`` is the raw diarization label (e.g. ``"S00"``).
    - Returns the identity key to store on ``SpeechSegment.speaker``.  MUST
      be deterministic for the same (file_key, local id) within one run.
    - Implementations must not assume speaker index 0 is any particular
      person, and must not merge IDs without evidence.
    """

    def resolve(self, file_key: str, local_speaker_id: str) -> str: ...


class PassthroughSpeakerIdentityResolver:
    """默认解析器：不推断身份，直接使用 file-local ID。"""

    def resolve(self, file_key: str, local_speaker_id: str) -> str:
        return str(local_speaker_id or "S00")


_GLOBAL_RESOLVER: SpeakerIdentityResolver = PassthroughSpeakerIdentityResolver()


def speaker_identity_resolver() -> SpeakerIdentityResolver:
    return _GLOBAL_RESOLVER


def set_speaker_identity_resolver(resolver: SpeakerIdentityResolver) -> None:
    global _GLOBAL_RESOLVER
    _GLOBAL_RESOLVER = resolver
