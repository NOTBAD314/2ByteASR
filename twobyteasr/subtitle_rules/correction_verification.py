"""Rank candidates by stable identity in both A/B orders, without writing text."""
from __future__ import annotations

import json

PROMPT_VERSION = 'zh-correction-second-opinion-v4-manual-review'
VERIFIABLE_RULES = frozenset({'catalog_without_local_support', 'local_difference_without_two_sources'})
# Wording, not mishearing: the speaker's own interjection stays as recognized.
INTERJECTIONS = frozenset({'我靠', '我操', '卧槽', '我草', '握草', '我去', '靠', '操', '草', '妈的', '他妈', '尼玛',
                           '哎呀', '哎呦', '哎哟', '天哪', '天呐'})
BATCH = 40
CONTEXT_CHARS = 40

SCHEMA = {'type': 'object', 'properties': {'answers': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'id': {'type': 'string'}, 'reason': {'type': 'string'}, 'better': {'type': 'string', 'enum': ['A', 'B', 'uncertain']}},
    'required': ['id', 'better', 'reason']}}}, 'required': ['answers']}


def system_prompt(domain):
    scene = f"《{domain}》相关视频" if domain else "视频"
    return (
        f"你在核对{scene}的语音识别字幕。每题给出同一句话的两个版本 A 和 B，只有一处用词不同。"
        "语音识别常把专有名词（技能、角色、道具）听成发音相近的普通词。"
        "判断说话人实际说的更可能是哪一个：哪个版本在这句话和前后文里意思通顺、合乎语境。"
        "如果两个都通顺，选更像普通口语、不需要术语也说得通的那个；如果有一个版本读起来字句不通，选另一个。"
        "terms 是本视频的术语，只作参考，不代表一定要换成术语。before和after是前后文，只作参考。"
        "两种解释皆缺证据或均不通顺时返回 uncertain。没有原音不能声称听到词语。"
        '只输出JSON对象{"answers":[{"id":"照录候选ID","reason":"一句话","better":"A"/"B"/"uncertain"}]}。')


def candidates(segments):
    """[(segment index, edit, start, end)] of rejected edits worth a second opinion."""
    found = []
    for index, segment in enumerate(segments):
        receipt = (getattr(segment, 'caption_arbitration', {}) or {}).get('terminology_polish') or {}
        text = segment.text
        for edit in receipt.get('rejected_edits', ()):
            source, target = str(edit.get('from') or ''), str(edit.get('to') or '')
            if (edit.get('rule_id') not in VERIFIABLE_RULES or not source or len(target) < 2 or source == target
                    or source in INTERJECTIONS or target in INTERJECTIONS):
                continue
            start, end = edit.get('start'), edit.get('end')
            if not (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                    and text[start:end] == source):
                continue
            found.append((index, edit, start, end))
    return found


def _ask(provider, snapshot, domain, terms, items, cancel_check):
    body = dict(prompt_version=PROMPT_VERSION, terms=terms, items=items)
    messages = [dict(role='system', content=system_prompt(domain)),
                dict(role='user', content=json.dumps(body, ensure_ascii=False, separators=(',', ':')))]
    response = provider.complete(messages, stage='polished', operation_kind='polish', batch_index='second-opinion',
                                 max_tokens=min(8192, 128+80*len(items)), temperature=0.,
                                 timeout=snapshot.timeout_policy.total, _timeout_policy=snapshot.timeout_policy,
                                 cancel_check=cancel_check, enable_thinking=False,
                                 thinking_protocol=snapshot.thinking_protocol,
                                 response_format={'type': 'json_object'}, json_schema=SCHEMA,
                                 structured_retry_system_prompt=None, structured_retry_max_tokens=())
    raw = str(response or '').strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    offered = {item['id'] for item in items}
    output, duplicates = {}, set()
    for row in json.loads(raw).get('answers', ()):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] not in offered:
            continue
        identifier = row['id']
        if identifier in output:
            duplicates.add(identifier)
        choice, reason = row.get('better'), row.get('reason')
        output[identifier] = (choice, reason) if choice in ('A', 'B', 'uncertain') and isinstance(reason, str) and reason.strip() else ('uncertain', '')
    return {key: value for key, value in output.items() if key not in duplicates}


def verify_rejected_edits(segments, snapshot, *, domain='', record=None, cancel_check=lambda: False, provider=None):
    """Attach strictly diagnostic rankings to existing candidates."""
    from ..recognition.service import CancelledError
    from ..glossary.source_review_policy import proposal_identity

    record = record or (lambda *_a, **_k: None)
    found = candidates(segments)
    if not found:
        return 0
    if provider is None:
        from ..providers.ai_providers import provider_for_stage
        from ..providers.llm_adapter import post_chat_completion
        try:
            provider = provider_for_stage(snapshot.execution_settings(), 'polish', sender=post_chat_completion)
        except CancelledError:
            raise
        except Exception as exc:
            record('correction_second_opinion_failed', error=str(exc)[:200])
            return 0
    terms = sorted({str(edit.get('to')) for _i, edit, _a, _b in found})
    items = []
    sources = {}
    for index, edit, start, end in found:
        text = segments[index].text
        identifier = proposal_identity(segments[index].segment_id, text, start, end, edit['to'])
        if identifier in sources:
            continue
        sources[identifier] = (index, edit)
        before = ''.join(s.text for s in segments[max(0, index-2):index])[-CONTEXT_CHARS:]
        after = ''.join(s.text for s in segments[index+1:index+3])[:CONTEXT_CHARS]
        # Plain sentences: brackets made an original cut across words look
        # broken (触梦的【话相】当于) and pulled the verdict to the term.
        original = text
        corrected = text[:start] + edit['to'] + text[end:]
        items.append((identifier, before, original, corrected, after))
    verdicts = {}
    failures = 0
    for offset in range(0, len(items), BATCH):
        chunk = items[offset:offset+BATCH]
        # Two independent readings (the second lists the items in reverse),
        # each asking both orders: the model was not stable even at
        # temperature 0, so a wrong edit must win all four answers.
        try:
            answers = []
            for rows in (chunk, chunk[::-1]):
                answers.append((_ask(provider, snapshot, domain, terms,
                    [dict(id=n, before=b, A=o, B=c, after=a) for n, b, o, c, a in rows], cancel_check), 'B'))
                answers.append((_ask(provider, snapshot, domain, terms,
                    [dict(id=n, before=b, A=c, B=o, after=a) for n, b, o, c, a in rows], cancel_check), 'A'))
        except CancelledError:
            raise
        except Exception as exc:  # these edits stay rejected
            failures += 1
            record('correction_second_opinion_failed', error=str(exc)[:200])
            continue
        for identifier, *_rest in chunk:
            votes = []
            for found_answers, candidate_slot in answers:
                choice, reason = found_answers.get(identifier, ('uncertain', ''))
                decision = 'candidate' if choice == candidate_slot else 'original' if choice in {'A','B'} else 'uncertain'
                votes.append(dict(candidate_slot=candidate_slot, choice=choice, decision=decision, reason=reason))
            identities = {vote['decision'] for vote in votes}
            verdicts[identifier] = dict(decision=identities.pop() if len(identities) == 1 else 'uncertain', votes=votes,
                proposal_id=identifier, acoustic_verified=False, prompt_version=PROMPT_VERSION)
    supported = 0
    for identifier, verdict in verdicts.items():
        index, edit = sources[identifier]
        receipt = segments[index].caption_arbitration.setdefault('terminology_polish', {})
        receipt.setdefault('second_opinion_verdicts', []).append(dict(verdict, patch=dict(edit)))
        supported += verdict['decision'] == 'candidate'
    record('correction_second_opinion', prompt_version=PROMPT_VERSION, candidates=len(sources), applied=0,
           candidate_preferred=supported, actor='background_analysis',
           failed_requests=failures)
    return supported
