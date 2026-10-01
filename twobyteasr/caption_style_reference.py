"""Curated visual evidence, kept separate from author artwork and media.

The shipped atlas is an original vector material study, never an asset to
paste in a subtitle. A request snapshots it so retry uses the same evidence.
No network, hidden model call, or user-data migration happens here.
"""
import hashlib
import json
import re
from pathlib import Path

VERSION = 'caption-style-reference-1'
CATEGORIES = {'joker', 'legendary', 'card_detail', 'chips_mult',
              'rarity_sticker', 'foil', 'panels_buttons'}


def is_balatro(prompt):
    return bool(re.search(r'(?<![a-z])balatro(?![a-z])|小丑牌|赌场\s*纸牌|传奇\s*卡牌|传奇\s*封牌', str(prompt), re.I))


def load_reference(prompt, *, root=None):
    if not is_balatro(prompt):
        return None
    if root is None:
        from .runtime_paths import detect_install_root
        root = detect_install_root()
    folder = Path(root) / 'assets/design-references/balatro'
    try:
        raw = (folder / 'manifest.json').read_bytes()
        manifest = json.loads(raw)
        if manifest['version'] != 'balatro-reference-1' or not CATEGORIES <= set(manifest['categories']):
            raise ValueError('图像类别不完整')
        atlas = folder / manifest['atlas']['file']
        if atlas.parent.resolve() != folder.resolve():
            raise ValueError('图像路径超出参考包')
        data = atlas.read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest['atlas']['sha256']:
            raise ValueError('图像指纹不符')
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ValueError('Balatro视觉参考包缺失或损坏，请恢复参考包后生成；尚未调用模型') from exc
    return dict(manifest=manifest, manifest_sha256=hashlib.sha256(raw).hexdigest(),
                path=str(atlas), data=data, manifest_bytes=raw)


def attach_reference(ledger, *, root=None):
    pack = load_reference(ledger.value['raw_user_prompt'], root=root)
    if not pack:
        return
    from .caption_creative_pipeline import reference_record, canonical, digest
    folder = ledger.root / 'style-reference'
    folder.mkdir(exist_ok=True)
    path = folder / 'balatro-reference.jpg'
    path.write_bytes(pack['data'])
    (folder / 'manifest.json').write_bytes(pack['manifest_bytes'])
    ledger.value['reference_files'].append(reference_record(path, 'style-reference'))
    ledger.value['style_reference'] = dict(version=VERSION, theme='Balatro',
        manifest_sha256=pack['manifest_sha256'], manifest=pack['manifest'],
        atlas_sha256=pack['manifest']['atlas']['sha256'],
        source=pack['manifest'].get('origin_kind', 'curated-published-images'), new_web_search_this_request=False,
        model_pixels_seen_confirmed=False)
    ledger.value['cache_key'] = digest(canonical([ledger.value['cache_key'],
        pack['manifest_sha256'], pack['manifest']['atlas']['sha256']]))
    ledger.save()


def prompt_reference(ledger):
    if not is_balatro(ledger.value['raw_user_prompt']):
        return None
    saved = ledger.value.get('style_reference')
    pack = None if saved else load_reference(ledger.value['raw_user_prompt'])
    manifest = saved['manifest'] if saved else pack['manifest']
    return dict(theme='Balatro', sampled_at=manifest['sampled_at'],
        source=manifest['primary_source'], categories=manifest['categories'],
        observations=manifest['observations'], transfer=manifest['transfer'],
        input_kind='curated visual observations; atlas only when attached',
        images_are_reference_not_artwork=True,
        model_pixels_seen_confirmed=False)


def direction_guidance(count):
    if count != 3:
        return '按本次要求在倍率封签、筹码压印或传奇封牌中选择适合的结构并充分设计；字幕本体承担风格。'
    return ('三个候选分别为A倍率封签、B筹码压印、C传奇封牌。'
            '必须改变结构、表面材质、关键词处理和动作节奏，不只换色。'
            '组件草案优先version:5，typeEffect与transition独立选crt/score/foil：A structure=seal/surface=paper/keyword=mult/motion=deal；'
            'B structure=table/surface=felt/keyword=chip/motion=press；'
            'C structure=legend/surface=foil/keyword=sticker/motion=sleeve。'
            '这些是可扩展方向；完整源码仍可自行实现同类视觉语法。')


def validate_draft_diversity(directions, prompt):
    """Reject a mislabeled color swap; never substitute host designs silently."""
    rows = directions.get('candidates', [])
    if not is_balatro(prompt) or len(rows) != 3 or not all('components' in r for r in rows):
        return
    for axis in ('structure', 'surface', 'keyword', 'motion'):
        values = [r['components'].get(axis) for r in rows]
        if None in values or len(set(values)) != 3:
            raise ValueError('Balatro三草案需要不同的' + axis + '；仅换配色不构成不同候选，原响应已保存')
