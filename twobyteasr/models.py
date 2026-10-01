"""Shared data objects used across recognition, timing, and export stages."""

from dataclasses import dataclass, field


@dataclass
class SubtitleCue:
    cue_id: int
    start: float
    end: float
    text: str
    timing_locked: bool = False
    speaker: str = "S00"


@dataclass
class WordUnit:
    start: float
    end: float
    text: str
    probability: float


@dataclass
class SpeechSegment:
    segment_id: int
    start: float
    end: float
    text: str
    confidence: float
    words: list
    speaker: str = "S00"
    moss_text: str = ""
    moss_context: str = ""
    firered_llm_text: str = ""
    firered_llm_context: str = ""
    alternate_text: str = ""
    alternate_context: str = ""
    qwen_asr_text: str = ""
    qwen_asr_context: str = ""
    overlapping_speaker_conflict: bool = False
    timing_locked: bool = False
    firered_text: str = ""
    moss_start: float = 0.0
    moss_end: float = 0.0
    firered_start: float = 0.0
    firered_end: float = 0.0
    firered_alignment_confidence: float = 0.0
    qwen_text: str = ""
    qwen_confidence: float = 0.0
    final_text: str = ""
    final_start: float = 0.0
    final_end: float = 0.0
    final_text_owner: str = "MOSS"
    final_timing_owner: str = "MOSS"
    primary_source: str = "moss-host"
    reference_consensus: float = 0.0
    caption_arbitration: dict = field(default_factory=dict)
