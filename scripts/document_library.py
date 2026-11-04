"""Build/check/search the repository's document navigation without dependencies.

Only git-listed paths are considered; ignored runtime/user directories are never
walked. Classification describes document purpose, not whether a feature works.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]
MANAGED = {'docs/CATALOG.md', 'docs/library.html'}
CONFIG = 'docs/document-library-overrides.json'
EXCLUDED_ROOTS = {
    'tmp', 'reports', '2ByteASR Projects', 'models', 'dist', 'build',
    'archive', 'backups', 'tools', 'wheels', 'node_modules', 'output',
    'outputs', '.agents', '.codex', '.git', 'prototype',
}
ENTRY_DOCS = [
    'docs/README.md', 'docs/PROJECT_STATE.md', 'docs/RECENT_CHANGES.md',
    'docs/TASKS.md', 'docs/GLOSSARY.md', 'docs/WRITING_GUIDE.md',
    'docs/adr/0097-readable-document-library.md',
]
TOPICS = {
    '识别与字幕文字': ('recognition', 'asr', 'transcribe', 'moss', 'firered', 'qwen', '识别', '转写', '文字', '断句', '校对', 'segmentation', 'grouping'),
    '播放与时间对齐': ('playback', 'timing', 'sync', 'flv', 'clock', 'seek', 'pts', 'follower', 'boundary', 'filmstrip', '播放', '同步', '时间', '空隙', '字幕不同步'),
    '编辑与导出': ('studio', 'edit', 'export', 'clip', 'razor', 'ripple', 'cue', 'cut', '编辑', '导出', '剪辑', '工作台'),
    '说话人与人名': ('speaker', 'diari', 'identity', 'names', 'overlap', '说话人', '身份', '人名', '重叠', '插话'),
    '模型与下载': ('model', 'workshop', 'download', 'runtime', 'storage', 'vibevoice', '模型', '工坊', '下载', '存储', '环境'),
    'AI 与字效设计': ('design', 'motion', 'theme', 'caption', 'authored', 'cover', 'balatro', 'pixel', 'preview', '字效', '动效', '特效', '设计', '封面', '主题'),
    '安装、更新与公开发行': ('release', 'packag', 'setup', 'installer', 'license', 'legal', 'gpl', 'source', 'macos', 'deploy', '安装', '发布', '更新', '许可', '分发', '公开'),
    '界面与操作': ('ui', 'ux', 'window', 'shortcut', 'keyboard', 'i18n', 'localization', 'visual', '界面', '窗口', '快捷键', '语言'),
    '项目进展与文档': ('document', 'catalog', 'plan', 'state', 'changelog', 'progress', 'readme', 'verification', 'audit', '文档', '进展', '状态', '变化', '检查', '待办'),
}
ALIASES = {
    '字幕不同步': ['同步', 'sync', 'timing', 'flv', '对齐'],
    '模型下载': ['模型', 'download', 'workshop', '存储'],
    '下载目录': ['模型目录', 'storage', '存储', '下载'],
    '声音不同步': ['音频', 'audio', 'sync', '同步'],
    '说话人认错': ['speaker', 'identity', '身份', '说话人'],
    '卡顿': ['性能', 'performance', 'playback', '播放'],
    '几天没看': ['近期变化', '当前状态', '进展'],
    '最近变化': ['近期变化', '最新', '状态'],
    '没做完': ['待办', '剩余', '验收'],
    '窗口恢复': ['最小化', 'window', '窗口', '恢复'],
    '字幕消失': ['visibility', '字幕', '显示'],
    '断句不好': ['断句', 'grouping', 'segmentation'],
}
PLAIN_WORDS = {
    'Architecture Decision Records': '长期决定', 'Architecture': '工作原理',
    'Active Plan': '任务记录', 'Completed Plan': '归档任务',
    'ProviderSnapshot': 'AI服务方案记录', 'Provider': 'AI服务',
    'Build Truth': '程序与源码核对', 'BuildTruth': '程序与源码核对',
    'MotionSpec': '动作方案', 'DesignSpec': '设计方案', 'Validator': '规则检查',
    'contract': '约定', 'receipt': '检查记录', 'frozen': '打包程序',
    'offscreen': '不显示窗口的测试', 'headed': '真实窗口检查',
    'ASR': '语音识别', 'Recognition': '语音识别', 'NLE': '视频编辑',
    'LIVE': '实时预览', 'Fidelity': '完整效果预览', 'Studio': '字幕工作台',
    'cue': '字幕条目', 'worker': '辅助进程', 'runtime': '运行环境',
    'follower': '叠加轨播放器', 'filmstrip': '视频缩略图',
    'schema': '数据结构', 'tokens': '配置项', 'token': '计量单位',
    'IPC': '程序之间通信', 'JSON': '结构化数据', 'PTS': '素材时间标记',
    'PCM': '音频样本', 'EOF': '媒体结束', 'VAD': '有说话的区段',
    'HTTP': '网络请求', 'CLI': '命令行连接', 'API': '服务接口',
    'UI': '界面', 'UX': '使用体验', 'EXE': 'Windows程序',
    '所有权': '职责', '真相源': '统一依据', '事实源': '主要依据',
    '回执': '检查记录', '契约': '约定', '原子': '整体',
    '生产': '实际运行', '冻结': '打包', '仲裁': '结果对照',
    '清关': '使用条件核对', '签收': '验收', '门控': '检查条件',
    '收口': '收尾', '自举': '环境准备', '字级': '每个字的',
}


def git_paths():
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT, capture_output=True, check=True,
    )
    return sorted(set(p for p in result.stdout.decode('utf-8').split('\0') if p))


def is_document(name):
    parts = Path(name).parts
    if not parts or parts[0] in EXCLUDED_ROOTS or any(
        x.startswith('.venv') or x in {'node_modules', '__pycache__'} for x in parts
    ):
        return False
    if name in MANAGED:
        return False
    if Path(name).suffix.lower() in {'.md', '.rst'}:
        return True
    if Path(name).suffix.lower() == '.txt':
        return parts[0] in {'docs', 'licenses', 'third_party'} or 'LICENSE' in Path(name).name.upper()
    return Path(name).name in {'LICENSE', 'NOTICE', 'COPYING'}


def purpose(name):
    if 'pre-gpl-' in name:
        return '历史许可说明', True, '这份方案已被后来的许可决定接替，只供追溯，不能作为当前使用条件。'
    if name.startswith(('docs/releases/', 'docs/testing/')):
        return '旧版本说明', True, '查看该版的说明与检查范围；不代表最新本机程序或公开安装包。'
    if name.startswith('third_party/'):
        return '上游资料', True, '第三方项目提供的原文；了解该组件，不据此判断兔白字幕当前状态。'
    if name.startswith(('licenses/materials/', 'licenses/source-materials/')) or Path(name).name in {'LICENSE', 'NOTICE', 'COPYING'}:
        return '许可原文', True, '使用或分发条件的原始文字，摘要不能代替原文。'
    if name.startswith(('docs/reports/archive/', 'audits/')):
        kind = '原始检查资料' if '/evidence/' in name or Path(name).suffix.lower() == '.txt' else '历史调查'
        return kind, True, '追溯当时的问题、检查或调查；日期较早的结论不代表现在。'
    if name.startswith('docs/exec-plans/completed/'):
        return '已归档任务记录', True, '查看那一轮做了什么及验证范围；归档不代表后来每版都已复验。'
    if name.startswith('docs/exec-plans/active/'):
        return '未归档任务记录', False, '查看目标、最后进展和未验条件；位置不自动代表仍在施工或全部完成。'
    if name.startswith('docs/adr/'):
        return '长期决定', False, '了解为什么选择这种做法，以及维护者需要遵守的约定。'
    if name.startswith('docs/architecture/') or name == 'ARCHITECTURE.md':
        return '实现说明', False, '先了解处理过程，再按需找实现细节；最新进展看当前状态页。'
    if name.startswith('licenses/optional-models/') and not name.endswith('CURRENT_STATUS.md'):
        return '历史许可说明', True, '已经移除模型的许可与来源保全资料；不是当前模型的可用性说明。'
    if name.startswith(('docs/legal/', 'licenses/')) or name in {'PROJECT_LICENSE.md', 'THIRD_PARTY_NOTICES.md', 'SOURCE_DELIVERY.md', 'SOURCE_ONLY_SCOPE.md'}:
        return '许可与分发说明', False, '查使用条件、来源与分发范围；是否已满足条件要看最新记录。'
    if name.startswith('releases/'):
        return '本机交付说明', True, '查某次本机交付与恢复，附件可能仅在本机或已归档。'
    if name.startswith(('examples/', 'assets/', 'website/', 'renderer/')):
        return '素材与展示说明', False, '了解这份素材、字幕样例或展示网页如何制作和使用。'
    if name in ENTRY_DOCS or name == 'AGENTS.md':
        return '项目与文档入口', False, '按问题了解当前进展或文档维护方式。'
    return '使用与维护说明', False, '查操作步骤、配置、环境准备或维护办法。'


def plain_title(title):
    title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', title)
    title = title.lstrip('> ').replace('**', '').replace('`', '')
    title = re.sub(r'^ADR[ -]?\d+[：:. ·—-]*', '', title, flags=re.I)
    title = re.sub(r'^\d{4}\s*[：·—]\s*', '', title)
    for word, replacement in PLAIN_WORDS.items():
        pattern = re.escape(word) if re.search(r'[\u4e00-\u9fff]', word) else r'(?<![A-Za-z])' + re.escape(word) + r'(?![A-Za-z])'
        title = re.sub(pattern, replacement, title, flags=re.I)
    return title.strip(' —:：')


def load_records():
    config = json.loads((ROOT / CONFIG).read_text(encoding='utf-8'))
    overrides = config['documents']
    records = []
    paths = git_paths()
    for name in paths:
        p = ROOT / name
        if not is_document(name) or not p.is_file():
            continue
        # Resolve only selected paths, refuse a link pointing outside the workspace.
        if not p.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Document resolves outside workspace: {name}')
        raw = p.read_bytes()
        text = raw.decode('utf-8-sig', errors='replace')
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')), '')
        if not title:
            lines = [line.strip() for line in text.splitlines()[:12] if line.strip()]
            title = lines[0][:160] if lines else p.stem
        kind, historic, explanation = purpose(name)
        custom = overrides.get(name, {})
        readable = custom.get('title', plain_title(title))
        # Keep the filename as identity when multiple originals just say README.
        if readable.lower() in {'readme', 'design', 'report', 'license', 'notice'}:
            readable = p.parent.name + '：' + explanation.split('；')[0]
        terms = ' '.join([name, title, readable, *custom.get('keywords', [])]).lower()
        tags = [tag for tag, tokens in TOPICS.items() if any(token in terms for token in tokens)]
        dates = re.findall(r'20\d{2}[-_]\d{2}[-_]\d{2}|20\d{6}', name)
        date = dates[0].replace('_', '-') if dates else ''
        if len(date) == 8:
            date = f'{date[:4]}-{date[4:6]}-{date[6:]}'
        records.append({
            'path': name, 'title': readable, 'originalTitle': title,
            'summary': custom.get('summary', explanation), 'kind': kind,
            'historic': historic, 'date': date, 'topics': tags,
            'keywords': custom.get('keywords', []),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'href': quote(os.path.relpath(p, ROOT / 'docs').replace('\\', '/'), safe='/'),
        })
    return config, records


def score(record, query):
    terms = query.lower().split()
    fields = ('title', 'originalTitle', 'summary', 'path')
    haystack = ' '.join([str(record[f]) for f in fields] + record['keywords'] + record['topics']).lower()
    total = 0
    for term in terms:
        if term in haystack:
            total += 20 + (40 if term in record['title'].lower() else 0) + (25 if term in record['keywords'] else 0)
        else:
            variants = ALIASES.get(term, [])
            if not any(v.lower() in haystack for v in variants):
                return 0
            total += 8
    return total if terms else 1


def render_catalog(config, records):
    lines = [
        '# 全部文档目录', '',
        f'整理日期：{config["reviewed_on"]}。共收录 **{len(records)}** 份说明、记录与原文。', '',
        '[按问题开始](README.md) · [当前状态](PROJECT_STATE.md) · [近期变化](RECENT_CHANGES.md) · [离线搜索](library.html)', '',
        '用页面查找搜索中文主题、原文件名或旧编号。这里的分类只说明文档用途，不宣布任务完成。', '',
        '第三方原文和原始检查资料单独列出；临时文件、模型、程序输出与用户工程不扫描。日期仅取文件名中明确的日期，空白表示文件名没有日期，不猜测交付时间。', '',
        '想搜索“字幕不同步”“模型下载”“没做完”等日常说法，请打开本地检索页。检索页搜索标题、说明、关键词和路径；需要逐字搜正文时，维护者可使用脚本的 `search --fulltext`。', '',
    ]
    kinds = list(dict.fromkeys(r['kind'] for r in records))
    priorities = ['项目与文档入口', '使用与维护说明', '实现说明', '未归档任务记录', '长期决定', '素材与展示说明', '许可与分发说明', '已归档任务记录', '本机交付说明', '旧版本说明', '历史调查', '原始检查资料', '历史许可说明', '许可原文', '上游资料']
    for kind in sorted(kinds, key=lambda k: priorities.index(k)):
        items = [r for r in records if r['kind'] == kind]
        lines.extend([f'## {kind}（{len(items)}）', '', '| 文档：白话标题 | 查什么／怎么用 | 主题与文件日期 |', '| --- | --- | --- |'])
        for r in sorted(items, key=lambda r: (r['date'], r['path']), reverse=kind in {'未归档任务记录', '已归档任务记录', '历史调查', '本机交付说明'}):
            clean = lambda s: re.sub(r'\s+', ' ', s).replace('|', '／').replace('[', '［').replace(']', '］')
            topics = '、'.join(r['topics']) or '按标题查找'
            label = clean(r['title'])
            lines.append(f'| [{label}]({r["href"]}) | {clean(r["summary"])}<br>原文件：`{r["path"]}` | {topics}<br>{r["date"] or "文件名无日期"} |')
        lines.append('')
    lines.extend(['<!-- Generated by scripts/document_library.py; edit source docs or overrides, then build. -->', ''])
    return '\n'.join(lines)


def render_html(config, records):
    template = (ROOT / 'scripts/document_library.template.html').read_text(encoding='utf-8')
    # Embed current project explanations so clicking Markdown does not trigger
    # browser downloads and reading still works from a file without a server.
    readable = {r['path']: (ROOT / r['path']).read_text(encoding='utf-8-sig', errors='replace')
                for r in records if not r['historic'] and r['kind'] not in {'许可原文', '许可与分发说明'}
                and Path(r['path']).suffix.lower() in {'.md', '.rst'}}
    payload = json.dumps({'documents': records, 'readable': readable, 'aliases': ALIASES, 'reviewedOn': config['reviewed_on']}, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('<', '\\u003c').replace('&', '\\u0026')
    return template.replace('@@DATA@@', payload).replace('@@COUNT@@', str(len(records))).replace('@@DATE@@', html.escape(config['reviewed_on']))


def check(config, records, expected):
    errors = []
    for name, text in expected.items():
        if not (ROOT / name).exists() or (ROOT / name).read_text(encoding='utf-8') != text:
            errors.append(f'目录已过期或不存在：{name}；先运行 build')
    record_paths = {r['path'] for r in records}
    for name in ENTRY_DOCS:
        if name not in record_paths:
            errors.append(f'入口没有收录：{name}')
    for r in records:
        target = ((ROOT / 'docs') / unquote(r['href'])).resolve()
        if target != (ROOT / r['path']).resolve() or not target.is_file():
            errors.append(f'目录链接不可达：{r["path"]}')
    # Check only authored entry documents, not rewrite inherited historic links.
    for name in ENTRY_DOCS:
        text = (ROOT / name).read_text(encoding='utf-8')
        for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)', text):
            if re.match(r'^(?:[a-zA-Z][\w+.-]*:|#|/)', target):
                continue
            target = unquote(target.split('#', 1)[0])
            if not ((ROOT / name).parent / target).exists():
                errors.append(f'入口链接不可达：{name} -> {target}')
    # A few practical questions must find their authoritative navigation or record.
    examples = {
        '字幕不同步': 'docs/exec-plans/active/2026-10-08-edited-flv-recognition-sync.md',
        '模型下载': 'docs/architecture/packaging.md',
        '没做完': 'docs/TASKS.md',
        '几天没看': 'docs/RECENT_CHANGES.md',
        '窗口恢复': 'docs/exec-plans/active/2026-10-08-studio-seven-issue-repair.md',
    }
    for query, target in examples.items():
        ranked = sorted((r for r in records if not r['historic'] and score(r, query)), key=lambda r: score(r, query), reverse=True)
        if target not in {r['path'] for r in ranked[:10]}:
            errors.append(f'检索前十项未找到预期说明：{query} -> {target}')
    result = {'documents': len(records), 'categories': dict(Counter(r['kind'] for r in records)), 'errors': errors, 'passed': not errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description='刷新、检查或搜索项目文档；不安装依赖，不扫描用户数据。')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build')
    sub.add_parser('check')
    search = sub.add_parser('search')
    search.add_argument('query')
    search.add_argument('--history', action='store_true', help='也搜索旧记录、许可原文和上游资料')
    search.add_argument('--fulltext', action='store_true', help='按输入词逐字搜索正文；不使用近义词扩展')
    search.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    config, records = load_records()
    if args.command == 'search':
        hits = []
        for r in records:
            if r['historic'] and not args.history:
                continue
            if args.fulltext:
                text = (ROOT / r['path']).read_text(encoding='utf-8-sig', errors='replace')
                terms = args.query.lower().split()
                if not terms or not all(term in text.lower() for term in terms):
                    continue
                rank = 1
                line = next((i for i, l in enumerate(text.splitlines(), 1) if any(t in l.lower() for t in terms)), 1)
            else:
                rank, line = score(r, args.query), 1
                if not rank:
                    continue
            hits.append((rank, r['date'], {**r, 'line': line}))
        hits.sort(key=lambda hit: (hit[0], hit[1]), reverse=True)
        print(json.dumps([h[2] for h in hits[:max(0, args.limit)]], ensure_ascii=False, indent=2))
        return 0
    expected = {'docs/CATALOG.md': render_catalog(config, records), 'docs/library.html': render_html(config, records)}
    if args.command == 'build':
        for name, text in expected.items():
            (ROOT / name).write_text(text, encoding='utf-8', newline='\n')
        print(json.dumps({'documents': len(records), 'generated': list(expected)}, ensure_ascii=False))
        return 0
    return check(config, records, expected)


if __name__ == '__main__':
    sys.exit(main())
