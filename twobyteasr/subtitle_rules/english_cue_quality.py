"""English cue boundaries inside the existing source/seconds contract.

One cue may occupy two visual lines. Wrapping belongs to renderers and must
not manufacture a new timeline item. Raw source slices preserve case, spaces,
punctuation and repeated words; time comes from the existing content timeline.
"""
from dataclasses import replace
import re

from .english_text import RULES
from .english_segmentation import split_tokens, break_scores

CUE_RULES = replace(RULES, max_chars=84, preferred_chars=60)
LONG_PAUSE = .8


def assemble(segments, proposed, aligned=()):
    from .segmentation import segment_content_timeline, hard_break_character_offsets
    from .text_rules import content_exact
    from .language_rules import CONTENT_CHAR_CLASS
    from subtitle_core import SubtitleCue, MIN_SUBTITLE_SECONDS
    raw = ''.join(segment.text for segment in segments)
    matches = list(re.finditer(r'\S+', raw))
    if not matches:
        return []
    timeline = [unit for segment in segments for unit in segment_content_timeline(segment, aligned)]
    positions = [match.start() for match in re.finditer(f'[{CONTENT_CHAR_CLASS}]', raw)]
    if len(timeline) != len(positions):
        raise ValueError('英文来源正文与时间单元不一致')
    # A punctuation-only token belongs to its neighbour, never its own cue.
    tokens, spans = [], []
    for match in matches:
        if content_exact(match.group()):
            tokens.append(match.group()); spans.append([match.start(), match.end()])
        elif spans:
            spans[-1][1] = match.end(); tokens[-1] = raw[slice(*spans[-1])]
    if not tokens:
        return []
    spans[0][0] = 0; spans[-1][1] = len(raw)
    content_ends = [len(content_exact(raw[:end])) for _, end in spans]
    content_starts = [len(content_exact(raw[:start])) for start, _ in spans]
    times = [(timeline[a].start, timeline[b-1].end) for a,b in zip(content_starts,content_ends)]
    gaps = [max(0, times[i+1][0]-times[i][1]) for i in range(len(tokens)-1)]
    scores = break_scores(tokens, gaps)
    forced_offsets = set(hard_break_character_offsets(segments, aligned))
    source_ends, cursor = set(), 0
    for segment in segments:
        cursor += len(content_exact(segment.text)); source_ends.add(cursor)
    wanted, cursor = set(), 0
    for text in proposed[:-1]:
        cursor += len(content_exact(text)); wanted.add(cursor)
    cuts = set()
    for index, offset in enumerate(content_ends[:-1],1):
        pause = gaps[index-1]
        if offset in forced_offsets or pause >= LONG_PAUSE:
            cuts.add(index)
        elif offset in wanted and (offset in source_ends or scores[index-1] >= 0):
            cuts.add(index)
    edges = [0, *sorted(cuts), len(tokens)]
    pieces = []
    for first, last in zip(edges,edges[1:]):
        # Including inter-word time prevents a sparse long span from passing
        # the duration check merely because its spoken words are short.
        durations = [max(0,times[i+1][0]-times[i][0]) if i+1<last else max(0,times[i][1]-times[i][0])
                     for i in range(first,last)]
        pieces.extend((first+a,first+b) for a,b in split_tokens(tokens[first:last], gaps[first:last-1],
                       durations=durations, rules=CUE_RULES))
    cues = []
    for first,last in pieces:
        text = raw[spans[first][0]:spans[last-1][1]].strip()
        start,end = times[first][0], times[last-1][1]
        cues.append(SubtitleCue(len(cues)+1, round(start,3), round(max(end,start+MIN_SUBTITLE_SECONDS),3),
                                text, all(getattr(x,'timing_locked',False) for x in segments), segments[0].speaker or 'S00'))
    from .grouping_contract import validate_grouping_result
    validate_grouping_result(segments, cues, minimum_seconds=MIN_SUBTITLE_SECONDS)
    from ..recognition.cache import record_run_event
    record_run_event('english_grouping_comparison', source=[s.text for s in segments], ai_proposed=list(proposed),
                     local=[c.text for c in cues], final=[{'text':c.text,'start':c.start,'end':c.end} for c in cues],
                     reason='word boundaries; 84-character cue capacity, 42-character visual line; real pauses retained')
    return cues
