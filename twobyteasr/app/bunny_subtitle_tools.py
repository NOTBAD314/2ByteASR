"""兔白's subtitle tools, round 4 (2026-11-16).

User (2026-11-15): make her a more useful agent — tune AI line breaks by talking, check the
subtitles and fix them, edit the text, learn from the user's own corrections, recipes, costs.
Registered in ``bunny_tools.TOOLS``; same contract (receipt, or (receipt, UndoRecord) for edits).

* Line-break preference: the user's words go into the existing 「断句偏好」 (settings
  ``grouping_prompts``) as one marked section after the built-in guidance, so the program's hard
  limits and the user's own edits there stay. Undoable while nobody changed it since.
* ``refine_cues`` runs the workbench's own AI 断句 on a few cues (a trial); when it finishes the
  chat posts a before/after comparison (``refine_report``).
* Authorized text edits use ``MutationOrigin.MODEL_ADOPTION``: they can update manually edited
  cues after permission handling, retain manual protection, and never feed human-correction learning.
"""
from __future__ import annotations

import time

SECTION = '【小兔纸的断句偏好（兔白照小兔纸的话写的，优先照这个）】'
RULE_LIMIT = 400
TRIAL_LIMIT = 30
MERGE_LIMIT = 4
TEXT_LIMIT = 200


# ------------------------------------------------------------------ settings and the line-break preference
def _settings() -> dict:
    try:
        import subtitle_core
        settings = getattr(subtitle_core, 'RUNTIME_SETTINGS', None)
        if isinstance(settings, dict):
            return settings
    except Exception:  # noqa: BLE001
        pass
    from ..storage.settings import load_runtime_settings
    loaded = load_runtime_settings()
    return loaded[0] if isinstance(loaded, tuple) else loaded


def _save(settings: dict) -> None:
    from ..storage.settings import save_runtime_settings
    save_runtime_settings(settings)


def break_language(window=None, language: str = '') -> str:
    """The prompt language her rule is for: asked, else the open project's, else the home page's."""
    from ..subtitle_rules.grouping_request import GROUPING_PROMPT_LANGUAGES
    from ..subtitle_rules.segmentation_profiles import profile_for, project_language_tag
    tag = str(language or '').strip()
    if not tag and window is not None:
        page = _built(window, 'studio')
        project = getattr(page, 'project', None)
        if project is not None:
            tag = project_language_tag(project)
    if not tag:
        tag = str((_settings().get('subtitle_language') or {}).get('recognition_language') or '')
    try:
        code = profile_for(tag or 'zh').code
    except Exception:  # noqa: BLE001
        code = 'zh'
    return code if code in GROUPING_PROMPT_LANGUAGES else 'zh'


def _stored(code: str) -> str:
    from ..subtitle_rules.segmentation_profiles import canonical_prompt_values
    prompts = _settings().get('grouping_prompts')
    values = canonical_prompt_values(prompts) if isinstance(prompts, dict) else {}
    return str(values.get(code) or '').strip()


def split_rules(text: str) -> tuple[str, str]:
    """(the guidance without her section, the user's rules in it)."""
    text = str(text or '')
    if SECTION not in text:
        return text.strip(), ''
    base, rules = text.split(SECTION, 1)
    return base.strip(), rules.strip()


def current_rules(code: str) -> str:
    return split_rules(_stored(code))[1]


def _write_rules(code: str, rules: str) -> tuple[object, object]:
    """Store ``rules`` (empty removes the section); (previous stored value, new stored value)."""
    from ..subtitle_rules.grouping_request import CUSTOM_GUIDANCE_MAX_CHARS, default_grouping_guidance
    settings = _settings()
    prompts = dict(settings.get('grouping_prompts') or {}) if isinstance(settings.get('grouping_prompts'), dict) else {}
    previous = prompts.get(code)
    default = default_grouping_guidance(code).strip()
    base = split_rules(_stored(code))[0] or default
    text = f'{base}\n{SECTION}\n{rules}' if rules else base
    if len(text) > CUSTOM_GUIDANCE_MAX_CHARS:
        raise ToolError('断句指引已接近长度上限，请先在设置中精简；原指引没有改动')
    value = '' if text.strip() == default else text
    prompts[code] = value
    settings['grouping_prompts'] = prompts
    _save(settings)
    return previous, value


def _limits_line(code: str) -> str:
    from ..subtitle_rules.segmentation_profiles import profile_for, unit_label
    profile = profile_for(code)
    try:
        unit = unit_label(code)
    except Exception:  # noqa: BLE001
        unit = '字'
    return (f'程序的硬上限：每条最多 {profile.hard_max:g} {unit}、{profile.max_seconds:g} 秒（偏好只能比它短，不能更长）；'
            f'一般 {profile.preferred:g} {unit}左右')


def _break_rules(window, args) -> str:
    code = break_language(window, args.get('language', ''))
    rules = current_rules(code)
    from ..subtitle_rules.grouping_request import custom_grouping_guidance
    other = split_rules(_stored(code))[0]
    from ..subtitle_rules.grouping_request import default_grouping_guidance
    edited = bool(custom_grouping_guidance(code, _settings())) and other and other != default_grouping_guidance(code).strip()
    lines = [f'语言：{code}', _limits_line(code),
             f'小兔纸的断句偏好：{rules}' if rules else '小兔纸的断句偏好：还没有（用的是内置规则）']
    if edited:
        lines.append('另外：小兔纸在「AI 智能断句设置」里自己改过断句指引（兔白只改自己那一段，不动他的）')
    lines.append('偏好对之后的识别和 AI 断句都生效；已经断好的字幕要重新跑 AI 断句才会照新的来'
                 '（AI 断句只会拆开太长的，不会把太短的合起来；要合用 merge_cues）')
    return '\n'.join(lines)


def _set_break_rule(window, args):
    code = break_language(window, args.get('language', ''))
    rules = ' '.join(str(args.get('rule') or '').split())[:RULE_LIMIT]
    old = current_rules(code)
    if rules == old:
        raise ToolError('断句偏好本来就是这样' if rules else '本来就没有断句偏好')
    previous, value = _write_rules(code, rules)

    def restore() -> str:
        settings = _settings()
        prompts = dict(settings.get('grouping_prompts') or {})
        if prompts.get(code) != value:
            return '断句偏好之后又被改过，兔白不敢乱撤；请到「AI 智能断句设置」里看'
        if previous is None:
            prompts.pop(code, None)
        else:
            prompts[code] = previous
        settings['grouping_prompts'] = prompts
        _save(settings)
        return ''
    said = f'把「{code}」的断句偏好{"改成" if rules else "清掉了，回到内置规则"}' + (f'：{rules}' if rules else '')
    return (said + '。之后的识别和 AI 断句都照这个；已经有的字幕要重跑 AI 断句（可以先 refine_cues 试几条）'
            '。在「AI 智能断句设置」里也看得到'), UndoRecord('call', restore, 0)


# ------------------------------------------------------------------ AI line breaks on a few cues (a trial)
def _numbers(project, args) -> list:
    cues = _cues(project)
    if not cues:
        raise ToolError('工程里没有字幕')
    wanted = args.get('numbers')
    if isinstance(wanted, (list, tuple)) and wanted:
        try:
            numbers = sorted({int(n) for n in wanted})
        except (TypeError, ValueError):
            raise ToolError('numbers 要给第几条的数字列表，例如 [3, 5, 9]') from None
    else:
        try:
            start = int(args.get('from') or 1)
            count = int(args.get('count') or 5)
        except (TypeError, ValueError):
            raise ToolError('from / count 要给数字') from None
        if count < 1 or count > TRIAL_LIMIT:
            raise ToolError(f'一次最多 {TRIAL_LIMIT} 条')
        numbers = list(range(start, start + count))
    numbers = [n for n in numbers if 1 <= n <= len(cues)]
    if not numbers:
        raise ToolError(f'没有这些字幕（一共 {len(cues)} 条）')
    if len(numbers) > TRIAL_LIMIT:
        raise ToolError(f'一次最多 {TRIAL_LIMIT} 条；整个工程用 ai_refine scope=all')
    return [(n, cues[n - 1]) for n in numbers]


def watch_refine(page, kind: str, picked) -> None:
    """Remember what the AI 断句 started on, so the chat can tell how it went (refine_report)."""
    page._bunny_refine_watch = dict(kind=kind, started=time.monotonic(),
                                    project=page.project, spans=[(n, cue.start_ms, cue.end_ms, cue.text) for n, cue in picked])


def _refine_cues(window, args):
    page = _studio(window)
    picked = _numbers(page.project, args)
    worker = getattr(page, '_refine_worker', None)
    if worker is not None and worker.isRunning():
        raise ToolError('AI 断句已经在跑了，等它做完')
    from ..providers.llm_config import text_ai_key_missing
    from ..storage.settings import load_runtime_settings
    settings = load_runtime_settings()
    settings = settings[0] if isinstance(settings, tuple) else settings
    if text_ai_key_missing(settings, 'group'):
        raise ToolError('还没填文字 AI 的 API Key（「AI 智能断句设置」）')
    if getattr(page.timeline, 'active_subtitle_layer', 'original') == 'translation':
        page.timeline.set_subtitle_layer('original')
    page.run_sentence_refine(whole_project=False, retry_ids=[cue.id for _n, cue in picked])
    started = getattr(page, '_refine_worker', None)
    if started is None or not started.isRunning():
        hint = getattr(getattr(page, 'save_state', None), 'text', lambda: '')()
        raise ToolError(f'AI 断句没开始{"：" + hint if hint else ""}')
    watch_refine(page, 'trial', picked)
    first, last = picked[0][0], picked[-1][0]
    return (f'开始用 AI 断句第 {first}' + (f'–{last}' if last != first else '') + f' 条（{len(picked)} 条，用小兔纸的 Key，'
            '按服务商计费）；做完兔白会贴出前后对照，不满意 Ctrl+Z 就回去')


def refine_report(page) -> list[str] | None:
    """How the watched AI 断句 went: lines for the chat, None while it runs, [] when nothing to say."""
    watch = getattr(page, '_bunny_refine_watch', None)
    if not watch:
        return []
    worker = getattr(page, '_refine_worker', None)
    if worker is not None and worker.isRunning():
        return None
    if time.monotonic() - watch['started'] < 0.5:
        return None
    page._bunny_refine_watch = None
    project = getattr(page, 'project', None)
    if project is None or project is not watch.get('project'):
        return []
    state = project.studio_state.get('ai_sentence_refine') or {}
    status = state.get('last_status', '')
    failed = len(state.get('failed_cue_ids') or ())
    if watch['kind'] != 'trial':
        if status in ('completed', 'partial', 'failed', 'cancelled'):
            return [{'completed': 'AI 断句做完啦～', 'partial': f'AI 断句做完了，还有 {failed} 条没成功，保留了原文。',
                     'failed': 'AI 断句没成功，原文都留着。', 'cancelled': 'AI 断句取消了，原文都留着。'}[status],
                    '不满意的话 Ctrl+Z 能整个退回。' if status in ('completed', 'partial') else '要兔白再试一次就说一声。']
        return []
    changed, kept = [], 0
    for number, start, end, before in watch['spans']:
        now = [cue.text for cue in _cues(project) if cue.start_ms >= start - 5 and cue.end_ms <= end + 5]
        after = ' | '.join(now) if now else ''
        if not now or after == before:
            kept += 1
            continue
        changed.append(f'第 {number} 条：{before[:24]} → {after[:40]}')
    if status == 'failed' and not changed:
        return ['试跑没成功，原文都留着。', (state.get('last_error') or '')[:60] or '要兔白再试一次吗？']
    lines = [f'试跑好了：{len(changed)} 条重新断了，{kept} 条照旧。'] + changed[:5]
    lines.append('满意的话说「全片都这样」，兔白就用 AI 断句整个工程；不满意按 Ctrl+Z。')
    return lines


# ------------------------------------------------------------------ health check
def _scope_ids(page, scope: str) -> list | None:
    if scope not in ('all', 'selected'):
        raise ToolError('scope 只能是 all 或 selected')
    if scope == 'selected':
        ids = list(page.selected_cue_ids())
        if not ids:
            raise ToolError('没有选中的字幕（可以用 scope=all 查全片）')
        return ids
    return None


def _check_subtitles(window, args) -> str:
    page = _studio(window)
    project = page.project
    if not project.cues:
        raise ToolError('工程里没有字幕')
    from ..subtitle_rules.studio_qc import SubtitleQCEngine, build_safe_fix_plan, terminology_from_project
    scope = str(args.get('scope') or 'all').strip()
    ids = _scope_ids(page, scope)
    result = SubtitleQCEngine().analyze(project, cue_ids=ids, terminology=terminology_from_project(project))
    number = {cue.id: index for index, cue in enumerate(_cues(project), 1)}
    groups: dict[str, list] = {}
    severities: dict[str, str] = {}
    rank = {'critical': 0, 'warning': 1, 'info': 2}
    for issue in result.issues:
        if issue.severity.value == 'info' and issue.category.value in ('asr', 'speaker'):
            continue                        # evidence notes for review, not problems to fix
        groups.setdefault(issue.label, []).append(number.get(issue.cue_id, 0))
        if rank.get(issue.severity.value, 2) < rank.get(severities.get(issue.label, 'info'), 2) or issue.label not in severities:
            severities[issue.label] = issue.severity.value
    lines = [f'查了{"选中的" if ids else "全片"} {len(ids) if ids else len(project.cues)} 条字幕']
    if not groups:
        lines.append('没发现要处理的问题')
    for label, numbers in sorted(groups.items(), key=lambda item: (rank.get(severities[item[0]], 2), -len(item[1])))[:10]:
        shown = '、'.join(str(n) for n in sorted(set(numbers))[:6])
        lines.append(f'- {label}：{len(set(numbers))} 条（第 {shown}{" 等" if len(set(numbers)) > 6 else ""} 条）'
                     + {'critical': '，较严重', 'info': '，小问题'}.get(severities[label], ''))
    plan = build_safe_fix_plan(project)
    if plan.total:
        counts = plan.counts
        lines.append(f'能安全自动修的：格式 {counts["text_format"]} 处、时间 {counts["timeline"]} 处、重复碎片 '
                     f'{counts["duplicate_fragment"]} 处（fix_subtitles 一步做完，可撤销）')
    failed = len((project.studio_state.get('ai_sentence_refine') or {}).get('failed_cue_ids') or ())
    if failed:
        lines.append(f'上次 AI 断句有 {failed} 条失败、保留了原文（ai_refine scope=failed）')
    return '\n'.join(lines)


def _fix_subtitles(window, args):
    page = _studio(window)
    from ..subtitle_rules.studio_qc import build_safe_fix_plan
    from ..timeline.studio_commands import ApplySafeFixesCommand
    plan = build_safe_fix_plan(page.project)
    if not plan.total:
        raise ToolError('没有能安全自动修的问题')
    before = page.undo_stack.index()
    page.undo_stack.push(ApplySafeFixesCommand(page.project, plan, page._changed))
    counts = plan.counts
    return (f'安全修复做完：格式 {counts["text_format"]} 处、时间 {counts["timeline"]} 处、重复碎片 '
            f'{counts["duplicate_fragment"]} 处（一步，Ctrl+Z 可以撤销）'), _pushed(page, before, '安全修复')


# ------------------------------------------------------------------ text edits
def _cue_number(project, value):
    cues = _cues(project)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError('number 要给第几条（从 1 开始）') from None
    if not 1 <= number <= len(cues):
        raise ToolError(f'没有第 {number} 条（一共 {len(cues)} 条）')
    return number, cues[number - 1]


def _clean_text(value) -> str:
    text = str(value if value is not None else '').replace('\r', '').strip()
    if not text:
        raise ToolError('新的文字是空的（删字幕兔白不做）')
    if len(text) > TEXT_LIMIT:
        raise ToolError(f'一条最多 {TEXT_LIMIT} 字')
    return text


def _edit_cue(window, args):
    page = _studio(window)
    number, cue = _cue_number(page.project, args.get('number'))
    text = _clean_text(args.get('text'))
    layer = str(args.get('layer') or 'original').strip()
    before = page.undo_stack.index()
    if layer == 'translation':
        from ..timeline.studio_commands import SetCueTranslationCommand
        old = str((page.project.generation_metadata.get('translations') or {}).get(cue.id, '') or '')
        if old == text:
            raise ToolError('译文本来就是这样')
        page.undo_stack.push(SetCueTranslationCommand(page.project, cue.id, text, page._changed))
        what = '译文'
    elif layer == 'original':
        from ..timeline.studio_commands import MutationOrigin, SetCueFieldsCommand
        old = cue.text
        if old == text:
            raise ToolError('原文本来就是这样')
        page.undo_stack.push(SetCueFieldsCommand(page.project, cue.id, {'text': text}, '兔白改字幕', page._changed,
                                                 origin=MutationOrigin.MODEL_ADOPTION))
        what = '原文'
    else:
        raise ToolError('layer 只能是 original（原文）或 translation（译文）')
    return f'第 {number} 条{what}：「{old[:30]}」→「{text[:40]}」（Ctrl+Z 可以撤销）', _pushed(page, before, '改字幕')


def _replace_text(window, args):
    page = _studio(window)
    find = str(args.get('find') or '')
    replace = str(args.get('replace') if args.get('replace') is not None else '')
    if not find.strip():
        raise ToolError('要给要换掉的字（find）')
    if find == replace:
        raise ToolError('换前换后一样')
    scope = str(args.get('scope') or 'all').strip()
    ids = set(_scope_ids(page, scope) or [cue.id for cue in page.project.cues])
    values = {cue.id: cue.text.replace(find, replace) for cue in page.project.cues if cue.id in ids and find in cue.text}
    if not values:
        raise ToolError(f'{"选中的" if scope == "selected" else "全片"}字幕里没有「{find}」')
    if any(not value.strip() for value in values.values()):
        raise ToolError('换完会有字幕变成空的，兔白不做；换个更具体的词')
    hits = sum(cue.text.count(find) for cue in page.project.cues if cue.id in values)
    from ..timeline.studio_commands import BatchReplaceTextCommand, MutationOrigin
    before = page.undo_stack.index()
    page.undo_stack.push(BatchReplaceTextCommand(page.project, values, needle=find, changed=page._changed,
                                                 origin=MutationOrigin.MODEL_ADOPTION))
    return (f'把「{find}」换成「{replace}」：{len(values)} 条字幕、{hits} 处（一步，Ctrl+Z 可以撤销）',
            _pushed(page, before, '替换'))


def _merge_cues(window, args):
    page = _studio(window)
    first, _cue = _cue_number(page.project, args.get('from'))
    last, _cue = _cue_number(page.project, args.get('to', first + 1))
    if last <= first:
        raise ToolError('to 要比 from 大（合并第 from 到第 to 条）')
    if last - first + 1 > MERGE_LIMIT:
        raise ToolError(f'一次最多合 {MERGE_LIMIT} 条')
    cues = _cues(page.project)[first - 1:last]
    if len({cue.speaker_id for cue in cues}) > 1:
        raise ToolError('这几条不是同一个说话人，不合')
    from ..timeline.studio_commands import merge_cues_command
    before = page.undo_stack.index()
    try:
        page.undo_stack.push(merge_cues_command(page.project, [cue.id for cue in cues], page.cue_controller.model_changed))
    except ValueError as exc:
        raise ToolError(f'合不了：{exc}') from None
    joined = ''.join(cue.text for cue in cues)
    return f'把第 {first}–{last} 条合成一条：「{joined[:40]}」（Ctrl+Z 可以撤销）', _pushed(page, before, '合并')


# ------------------------------------------------------------------ learning from the user's own corrections
def learned_pairs(page, limit: int = 6) -> list[dict]:
    store = getattr(page, '_learning_store', None)
    if store is None:
        return []
    try:
        candidates = store.load().get('candidates') or []
    except Exception:  # noqa: BLE001
        return []
    rows = []
    texts = [cue.text for cue in getattr(getattr(page, 'project', None), 'cues', ())]
    for item in candidates:
        if item.get('status') not in ('pending', 'collecting') or int(item.get('occurrence_count', 0)) < 2:
            continue
        source, target = str(item.get('original_term') or ''), str(item.get('corrected_term') or '')
        if not source or not target:
            continue
        rows.append(dict(source=source, target=target, count=int(item.get('occurrence_count', 0)),
                         left=sum(text.count(source) for text in texts), status=item.get('status')))
    rows.sort(key=lambda row: (row['left'] == 0, -row['count']))
    return rows[:limit]


def learned_summary(page) -> str:
    rows = [row for row in learned_pairs(page, 3) if row['left']]
    return '；'.join(f'{row["source"]}→{row["target"]}（改过 {row["count"]} 次，这个工程还剩 {row["left"]} 处）' for row in rows)


def _learned_edits(window, _args) -> str:
    page = _studio(window)
    rows = learned_pairs(page)
    if not rows:
        return '还没有反复出现的手动修改（同一个改法改过 2 次以上才算）'
    lines = ['小兔纸自己反复改过的字（软件的术语学习记录）：']
    for row in rows:
        lines.append(f'- 「{row["source"]}」→「{row["target"]}」：改过 {row["count"]} 次，这个工程还剩 {row["left"]} 处'
                     + ('，已经等着进术语库' if row['status'] == 'pending' else ''))
    lines.append('剩下的可以用 replace_text 全片换掉；要软件以后识别时也自动改对，到「术语库」确认学习建议')
    return '\n'.join(lines)


# ------------------------------------------------------------------ recipes
def _recipe_from(page) -> dict:
    from ..subtitle_rules.segmentation_profiles import project_language_tag
    project = page.project
    cues = _cues(project)
    data: dict = {}
    if cues:
        from ..caption_style.style_resolution import resolve_cue_visual
        style = resolve_cue_visual(project, cues[0]).style
        data['style'] = dict(font_size=float(style.font_size), fill_color=str(style.primary_color).upper(),
                             outline_color=str(style.outline_color).upper(), outline_width=float(style.outline_width),
                             bold=bool(style.bold))
    code = break_language(None, project_language_tag(project))
    rules = current_rules(code)
    if rules:
        data['break_rule'] = rules
        data['language'] = code
    names = [str(speaker.name or '') for speaker in project.speakers if str(speaker.name or '').strip()]
    if names:
        data['speakers'] = names[:8]
    return data


def _save_recipe(window, args) -> str:
    from . import bunny_memory
    page = _studio(window)
    name = ' '.join(str(args.get('name') or '').split())[:20]
    if not name:
        raise ToolError('配方要有名字，例如「原神」')
    data = _recipe_from(page)
    if not data:
        raise ToolError('这个工程还没有能存的样式、断句偏好或说话人名')
    try:
        bunny_memory.add(name, 'recipe', source='bunny', data=data)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    try:
        from ..projects.series_store import SeriesStore
        store = SeriesStore()
        rec = store.find_by_name(name) or store.create(name)
        delta = store.compute_delta(
            rec.id,
            speakers=[{'name': n} for n in (data.get('speakers') or ())],
            break_rule=(data.get('language') or 'zh', data['break_rule']) if data.get('break_rule') else None,
            visual={'style_overrides': data['style']} if data.get('style') else None,
        )
        if delta:
            store.settle(rec.id, delta, episode_label='bunny_save_recipe')
    except Exception:  # noqa: BLE001 - Series mirror must never break legacy recipe save
        pass
    parts = []
    if 'style' in data:
        s = data['style']
        parts.append(f'样式（{s["font_size"]:g} 号、字 {s["fill_color"]}、描边 {s["outline_color"]} {s["outline_width"]:g}）')
    if 'break_rule' in data:
        parts.append(f'断句偏好「{data["break_rule"][:30]}」')
    if 'speakers' in data:
        parts.append('说话人名 ' + '、'.join(data['speakers']))
    return f'存好配方「{name}」：' + '；'.join(parts) + f'。下次说「照{name}那套」就能一起套上'


def _use_recipe(window, args):
    from . import bunny_memory
    from .bunny_tools import _apply_style, _rename_speaker
    page = _studio(window)
    name = ' '.join(str(args.get('name') or '').split())
    recipe = next((row for row in bunny_memory.load() if row['kind'] == 'recipe' and row['text'] == name), None)
    if recipe is None:
        known = '、'.join(row['text'] for row in bunny_memory.load() if row['kind'] == 'recipe') or '还没有配方'
        raise ToolError(f'没有叫「{name}」的配方（现在有：{known}）')
    data = recipe.get('data') or {}
    done, records = [], []
    try:
        if data.get('style'):
            receipt, record = _apply_style(window, dict(data['style'], scope='all'))
            done.append('样式套到全片')
            records.append(record)
        if data.get('break_rule'):
            code = break_language(window, data.get('language', ''))
            if current_rules(code) == data['break_rule']:
                done.append('断句偏好（本来就一样）')
            else:
                _receipt, record = _set_break_rule(window, {'rule': data['break_rule'], 'language': code})
                done.append('断句偏好')
                records.append(record)
        names = data.get('speakers') or []
        speakers = list(page.project.speakers)
        if names and len(speakers) == len(names):
            for speaker, new in zip(speakers, names):
                if str(speaker.name or '') != new:
                    _receipt, record = _rename_speaker(window, {'speaker': speaker.id, 'name': new})
                    records.append(record)
            done.append('说话人名')
        elif names:
            done.append(f'说话人名没套（这个工程有 {len(speakers)} 个说话人，配方里是 {len(names)} 个）')
    except Exception:
        from .bunny_tools import undo_records
        undo_records(records)
        raise
    if not records:
        raise ToolError('配方里的东西这个工程本来就一样')
    return f'照配方「{name}」套好了：' + '、'.join(done) + '（「撤销兔白刚才做的」能一起撤回）', UndoRecord('group', records, 0)


# ------------------------------------------------------------------ costs
def _rates(stage='group'):
    from datetime import datetime, timezone
    from ..providers.usage_ledger import price_snapshot
    from ..providers.llm_config import endpoint_from_settings
    endpoint = endpoint_from_settings(_settings(), stage)
    model = str(endpoint.get('model') or '')
    snapshot = price_snapshot(str(endpoint.get('base_url') or ''), model, datetime.now(timezone.utc).isoformat())
    return model, snapshot


def _estimate_cost(window, args) -> str:
    page = _studio(window)
    what = str(args.get('what') or 'refine_failed').strip()
    project = page.project
    if what == 'refine_failed':
        ids = set((project.studio_state.get('ai_sentence_refine') or {}).get('failed_cue_ids') or ())
        cues = [cue for cue in project.cues if cue.id in ids]
    elif what == 'refine_selected':
        ids = set(page.selected_cue_ids())
        cues = [cue for cue in project.cues if cue.id in ids]
    elif what in ('refine_all', 'translate_all'):
        cues = list(project.cues)
    else:
        raise ToolError('what 只能是 refine_failed / refine_selected / refine_all / translate_all')
    if not cues:
        raise ToolError('这个范围里没有字幕')
    chars = sum(len(cue.text) for cue in cues)
    batches = max(1, -(-len(cues) // 40))
    if what == 'translate_all':
        tokens_in, tokens_out = 2500 * batches + 3 * chars, 2 * chars + 30 * len(cues)
    else:
        tokens_in, tokens_out = 2500 * batches + 4 * chars, 60 * len(cues)
    model, price = _rates('polish' if what == 'translate_all' else 'group')
    head = f'{len(cues)} 条、{chars} 字，大约 {tokens_in // 1000 + 1}k 输入、{tokens_out // 1000 + 1}k 输出 token'
    if not price.get('known'):
        return head + f'；模型「{model or "没设置"}」兔白没有价目，没法估钱（以服务商页面为准）'
    from decimal import Decimal

    def cost(rates):
        return (Decimal(tokens_in) * Decimal(rates[1]) + Decimal(tokens_out) * Decimal(rates[2])) / Decimal(1_000_000)
    low, high = cost(price['rates_low']), cost(price['rates_high']) * Decimal('1.5')
    return (head + f'；按 {model} 已记录价目粗估 {low:.4f}–{high:.4f} 美元（'
            '没算缓存折扣和重试；以服务商账单为准）')


def _usage(window, _args) -> str:
    from datetime import datetime
    from decimal import Decimal
    from ..providers.usage_ledger import read_rows
    try:
        rows = read_rows()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f'读不到用量记录：{type(exc).__name__}') from None
    now = datetime.now()
    month, today = now.strftime('%Y-%m'), now.strftime('%Y-%m-%d')

    def total(selected):
        low = high = Decimal(0)
        unknown = 0
        for row in selected:
            cost = row.get('cost') or {}
            if cost.get('known'):
                low += Decimal(str(cost.get('low') or 0))
                high += Decimal(str(cost.get('high') or 0))
            else:
                unknown += 1
        return low, high, unknown
    this_month = [row for row in rows if str(row.get('at') or '')[:7] == month]
    this_day = [row for row in this_month if str(row.get('at') or '')[:10] == today]
    if not this_month:
        return f'{month} 还没有用文字 AI 的记录'
    lines = []
    for label, selected in (('今天', this_day), ('这个月', this_month)):
        low, high, unknown = total(selected)
        lines.append(f'{label}：{len(selected)} 次请求，估算 {low:.4f}' + (f'–{high:.4f}' if high != low else '')
                     + ' 美元' + (f'（{unknown} 次没有价目，没算进去）' if unknown else ''))
    stages: dict[str, int] = {}
    for row in this_month:
        stages[str(row.get('stage') or '其它')] = stages.get(str(row.get('stage') or '其它'), 0) + 1
    lines.append('这个月按步骤：' + '、'.join(f'{key} {value} 次' for key, value in sorted(stages.items(), key=lambda kv: -kv[1])[:5]))
    lines.append('这是软件按公开价算的估算，以服务商账单为准；详细的在「用量与费用」窗口')
    return '\n'.join(lines)


def tools() -> tuple:
    from .bunny_tools import Tool
    return (
        Tool('break_rules', '{}', '读 AI 断句的规则：程序硬上限（每条最多几个字、几秒）和小兔纸的断句偏好', _break_rules),
        Tool('set_break_rule', '{"rule": "每条尽量不超过10个字"}',
             '【修改】写小兔纸的断句偏好（整段替换，空字符串清掉；只写他说过的，已有的偏好要保留就一起写上）；对之后的识别和 AI 断句生效，可撤销。只能比硬上限更短、不能更长',
             _set_break_rule, edit=True),
        Tool('refine_cues', '{"from": 12, "count": 5}', '【花 Key】工作台：用 AI 断句其中几条（试跑新偏好、或修太长的；也可给 '
             '"numbers": [3, 8]，最多 30 条）；写回工程可 Ctrl+Z，做完兔白会自动贴前后对照', _refine_cues, paid=True),
        Tool('check_subtitles', '{"scope": "all"}', '工作台：字幕体检（all 全片 / selected 选中）：太长、太快读不完、时间太短或重叠、'
             '空白、重复、碎片……列出第几条，和能安全自动修的数量', _check_subtitles),
        Tool('fix_subtitles', '{}', '【修改】工作台：一步做完体检里「能安全自动修」的（格式、时间重叠/空隙、重复碎片），可撤销', _fix_subtitles,
             edit=True),
        Tool('edit_cue', '{"number": 12, "text": "新的文字", "layer": "original"}', '【修改】工作台：改第几条字幕的文字，layer=original 原文 '
             '/ translation 译文（改错字、润色译文、换口吻）；可撤销', _edit_cue, edit=True),
        Tool('replace_text', '{"find": "元神", "replace": "原神", "scope": "all"}', '【修改】工作台：全片（all）或选中的（selected）'
             '字幕里把某些字换掉（统一术语、错字、删口头禅），一步可撤销', _replace_text, edit=True),
        Tool('merge_cues', '{"from": 12, "to": 13}', f'【修改】工作台：把相邻的第 from 到第 to 条合成一条（同一个说话人，最多 {MERGE_LIMIT} 条），可撤销',
             _merge_cues, edit=True),
        Tool('learned_edits', '{}', '工作台：小兔纸自己反复手动改过的字（例如 元神→原神 改过 3 次），和这个工程还剩几处', _learned_edits),
        Tool('save_recipe', '{"name": "原神"}', '把这个工程的样式、断句偏好、说话人名存成一套配方（同名会更新）', _save_recipe),
        Tool('use_recipe', '{"name": "原神"}', '【修改】工作台：照配方把样式套到全片、写断句偏好、按顺序改说话人名，能一起撤销', _use_recipe,
             edit=True),
        Tool('estimate_cost', '{"what": "refine_failed"}', '工作台：粗估用文字 AI 要花多少（refine_failed / refine_selected / '
             'refine_all / translate_all）', _estimate_cost),
        Tool('usage', '{}', '今天和这个月文字 AI 用了多少次、估算花了多少钱（读软件的用量账本）', _usage),
    )


# Imported last: bunny_tools builds its TOOLS from tools() above while it is still loading.
from .bunny_tools import ToolError, UndoRecord, _built, _cues, _pushed, _studio  # noqa: E402

__all__ = ['SECTION', 'break_language', 'current_rules', 'learned_pairs', 'learned_summary', 'refine_report',
           'split_rules', 'tools', 'watch_refine']
