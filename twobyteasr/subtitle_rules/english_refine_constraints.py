"""English cue length and measured layout are separate, lossless constraints."""
import copy
import re


def effective_language(texts, declared):
    """Long clearly English islands do not inherit CJK character limits."""
    if str(declared).split('-')[0] not in {'zh','ja','ko','und'}: return declared
    texts=list(texts)
    if texts and all(sum(ch.isascii() and ch.isalpha() for ch in text)>=20
                     and len(text.split())>=4
                     and not any('\u3040'<=ch<='\u30ff' or '\u3400'<=ch<='\u9fff' or '\uac00'<=ch<='\ud7af' for ch in text)
                     for text in texts): return 'en'
    return declared


def visible_text(text):
    text = re.sub(r'\{\\[^{}]*\}|</?(?:b|i|u|font|span)\b[^>]*>', '', str(text), flags=re.I)
    return text.replace(r'\N', '').replace('\r', '').replace('\n', '')


def policy(cue, project=None):
    result = dict(language='en', cue_max=40, line_max=40, max_lines=2, source_fidelity='exact_source_order_and_characters')
    if project is not None:
        from ..caption_style.style_resolution import recipe_for_cue
        layout = (recipe_for_cue(project.style_recipes, cue) or {}).get('layout', {})
        for field, key in [('cue_max','maxCharsPerCue'), ('line_max','maxCharsPerLine'), ('max_lines','maxLines')]:
            value = layout.get(key)
            if isinstance(value, (int,float)) and 1 <= value <= 1000: result[field] = int(value)
    return result


def layout_text(cue, project=None):
    from .segmentation_profiles import measure
    from ..caption_style.caption_text_layout import wrap_caption_text
    limits = policy(cue, project)
    pixels = lambda text: 0.
    width = 1.
    if project is not None:
        from ..caption_style.resolved_caption_style import resolve_caption_style, _measurement_font
        caption = resolve_caption_style(project.styles, project.speakers, cue, project.style_recipes,
            int(project.render_settings.get('play_res_x',1920)), int(project.render_settings.get('play_res_y',1080)))
        style = caption.style
        face = caption.layout['font']
        font = _measurement_font(face['file'],1000,index=face.get('index',0))
        pixels = lambda text: (font.getlength(visible_text(text))/1000*style.font_size+max(0,len(visible_text(text))-1)*style.spacing)*style.scale_x/100.
        width = caption.max_width
    # One measurement enforces BOTH the character cap and physical safe area.
    layout = wrap_caption_text(cue.text, lambda text: max(measure(text,'en')/limits['line_max'], pixels(text)/width), 1.)
    return layout, limits, width


def validate_piece(text, cue, project=None, *, enforce_cue=True):
    from .segmentation_profiles import measure
    from .sentence_refine_contract import RefineError
    clone = copy.copy(cue); clone.text = text
    layout, limits, _ = layout_text(clone, project)
    if enforce_cue and measure(text,'en') > limits['cue_max']:
        raise RefineError(f'英语单条 {measure(text,"en")} 字符，超过 {limits["cue_max"]}（含空格标点；换行不扩充单条上限）','constraint_conflict')
    if layout.overflow or len(layout.lines) > limits['max_lines']:
        raise RefineError('英语字幕超过单行字符/画面安全宽度或最大行数；保留字号与原文', 'layout_conflict')
    return layout.text


def local_action(unit, project=None):
    """DP over supplied word/phrase boundaries; no raw character slicing."""
    from .sentence_refine import CueRefineAction
    from .sentence_refine_contract import RefineError
    from .segmentation_profiles import measure
    text = unit.cue.text
    edges = [0, *sorted({index+1 for index in unit.candidates.values()}), len(text)]
    best = {0: (0., [])}
    for right in edges[1:]:
        candidates = []
        for left in edges:
            if left >= right or left not in best: continue
            piece = text[left:right]
            try: validate_piece(piece, unit.cue, project)
            except RefineError: continue
            # Prefer complete, balanced phrases; candidates already exclude
            # protected contractions, words, decimal/unit and phrasal bonds.
            punctuation = text[:right].rstrip()[-1:] in '.!?;:,'
            score = best[left][0]+100+(40-measure(piece,'en'))**2*.08-(12 if punctuation else 0)
            candidates.append((score, [*best[left][1], right]))
        if candidates: best[right] = min(candidates, key=lambda value:value[0])
    if len(text) not in best:
        raise RefineError('完整网址、词语或不可拆意群超过长度/画面限制，保留原文；请手动处理此条','indivisible_overflow')
    return CueRefineAction(unit.cue.id, 'split', split_after_chars=[edge-1 for edge in best[len(text)][1][:-1]])


def wrap_action(unit, project=None):
    from .sentence_refine import CueRefineAction
    from .sentence_refine_contract import RefineError
    layout, limits, _ = layout_text(unit.cue, project)
    if layout.overflow or len(layout.lines)>limits['max_lines']:
        raise RefineError('缺少可靠字词时间；排版也无法在现有字号和最大行数内显示，请先对齐此条','time_mapping_error')
    return CueRefineAction(unit.cue.id, 'wrap', layout_text=layout.text, alignment_pending=True)
