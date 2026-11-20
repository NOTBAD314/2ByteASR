"""兔白 knowledge questions, asked for real (2026-11-18, knowledge base v2).

``bunny_eval`` checks that she can *do* things; this checks that she *knows* things: each question is
one a user would type, and the answer (her sentences plus the detail card) must name the facts in
``need`` — every group must have one of its spellings. It uses the user's own text AI (the key is
read in memory, never printed or written) and no window; ``search_knowledge`` runs for real, other
tools are refused so she answers from what she knows.

    python -X utf8 -m twobyteasr.acceptance.bunny_knowledge_eval [substring ...]

Report: ``tmp/bunny-eval/knowledge-<time>.json``. Exit code 0 when every question passes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

MAX_ROUNDS = 3
# (question, page, [groups]); a group is the spellings any one of which counts.
QUESTIONS = (
    ('安装时提示未知发布者，是不是有病毒？', '', [('签名',), ('仍要运行', '更多信息')]),
    ('界面的字太小了', '首页', [('Ctrl+=',)]),
    ('我没有 NVIDIA 显卡还能用吗？', '首页', [('云端',), ('轻量本机', 'CPU')]),
    ('模型下载到一半断了怎么办', '模型工坊', [('断点续传', '接着下', '续传')]),
    ('API Key 测试连接失败，401', '', [('Key',), ('空格', '贴错', '重新贴', '复制', '同一家', '余额', '开通')]),
    ('提示请求太频繁 429 是 Key 坏了吗', '', [('限流', '太频繁', '太快'), ('等', '重试')]),
    ('识别出来错字特别多怎么办', '识别完成的结果页', [('术语库', '词库'), ('只重新识别这一段', '质量优先', '文字复核', '批量替换')]),
    ('角色名字老是写错', '字幕工作台', [('术语库', '词库')]),
    ('字幕比声音慢半秒', '字幕工作台', [('Alt+←',), ('提前',)]),
    ('中间有一段没字幕', '字幕工作台', [('I', '入点', '入出点', '框起来', '框住'), ('只重新识别这一段字幕', '重新识别这一段')]),
    ('字幕里有好多没人说过的话', '字幕工作台', [('音乐', '噪音', '没人说话', '安静'), ('删', 'Delete', 'AI 清理', '重新识别')]),
    ('识别完显示有需复核项，是不是出错了', '识别完成的结果页', [('不是出错', '不是坏', '不是错'), ('R',)]),
    ('一条字幕太长了怎么切短', '字幕工作台', [('AI 断句', 'Shift+C', '剃刀')]),
    ('同一个错字到处都是，怎么一次改完', '字幕工作台', [('Ctrl+H', '批量替换')]),
    ('字幕挡住游戏血条了', '字幕工作台', [('拖', '位置与对齐')]),
    ('双语字幕只想把译文改成黄色', '字幕工作台', [('译文',), ('语言层', '下拉', '应用样式与动效', '译文显示样式')]),
    ('导出的 SRT 打开全是乱码', '', [('UTF-8',)]),
    ('压制的时候显卡编码失败了', '字幕工作台', [('CPU 编码', 'CPU编码', '改用 CPU')]),
    ('发 B 站应该导出 SRT 还是把字幕压进视频？', '字幕工作台', [('SRT',), ('导出音视频', '压进', '烧进')]),
    ('软件闪退了，没保存的还能找回吗', '', [('自动恢复', '自动保存')]),
    ('视频文件换了位置，工程里黑屏', '字幕工作台', [('重新定位源媒体',)]),
    ('卸载重装后模型要重新下载吗', '', [('保留', '还在', '不用重新', '不会删', '不会丢')]),
    ('字幕一行多少个字比较合适？', '', [('12', '13', '14', '15', '16')]),
    ('软字幕和硬字幕有什么区别', '', [('开关', '关不掉', '可以关'), ('画面', '烧')]),
    ('为什么云端识别的时间旁边写着估算', '字幕工作台', [('句段',), ('逐字', '字词', '对齐')]),
    ('兔白你为什么不直接帮我改，还要我按按钮', '', [('兔白权限', '权限'), ('帮我做',)]),
)


def _settings() -> dict:
    root = Path(os.environ.get('LOCALAPPDATA', '')) / '2ByteASR' / '2byteasr_settings.json'
    return json.loads(root.read_text(encoding='utf-8'))


def _said(reply) -> str:
    return '\n'.join((*reply.lines, *reply.detail))


def ask(provider, question: str, page: str, lore, features) -> dict:
    from twobyteasr.app import bunny_lore, bunny_persona
    from twobyteasr.app.bunny_tools import TOOLS, ToolError
    keys = [key for key, _title, _where in features]
    state = {'page': page or '首页', 'project_open': page == '字幕工作台', 'text_ai_ready': True}
    messages = bunny_persona.build_messages(
        question, features=features, core=bunny_lore.CORE,
        entries=bunny_lore.select_extra(question, lore, page=page), state=state,
        inner={'uneasy': 0, 'meme_ok': False, 'plot_ok': False})
    started, used, reply = time.monotonic(), [], None
    for _round in range(MAX_ROUNDS):
        text = provider.complete(messages, max_tokens=1400, temperature=0.3, timeout=(15, 120), stage='bunny_chat',
                                 enable_thinking=False, operation_kind='bunny_chat')
        reply = bunny_persona.parse_reply(text, keys)
        if not reply.tools:
            break
        receipts = []
        for name, args in reply.tools:
            used.append(name)
            if name == 'search_knowledge':
                try:
                    receipts.append(f'- {name}：成功。{TOOLS[name].run(SimpleNamespace(), args)}')
                except ToolError as error:
                    receipts.append(f'- {name}：没做成。{error}')
            else:
                receipts.append(f'- {name}：没做成。这是知识测验，这个工具现在用不了；照你知道的直接回答')
        messages = [*messages, {'role': 'assistant', 'content': text},
                    bunny_persona.tool_results_message(receipts, bunny_persona.format_state(state))]
    return {'reply': reply, 'seconds': round(time.monotonic() - started, 1), 'tools': used}


def grade(answer: str, need) -> list:
    """The groups the answer does not cover."""
    flat = answer.replace('**', '').replace('==', '')
    return [group for group in need if not any(word in flat for word in group)]


def main(argv=None) -> int:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from twobyteasr.app import bunny_lore
    from twobyteasr.providers.ai_providers import provider_for_stage
    wanted = list(argv if argv is not None else sys.argv[1:])
    provider = provider_for_stage(_settings(), 'polish')
    lore, features = bunny_lore.build_entries(), bunny_lore.feature_index()
    rows = []
    for question, page, need in QUESTIONS:
        if wanted and not any(word in question for word in wanted):
            continue
        try:
            result = ask(provider, question, page, lore, features)
            answer = _said(result['reply'])
            missing = grade(answer, need)
            row = {'question': question, 'page': page, 'passed': not missing, 'missing': [list(g) for g in missing],
                   'chars': len(answer), 'seconds': result['seconds'], 'tools': result['tools'], 'answer': answer}
        except Exception as error:  # noqa: BLE001 - one failed request must not end the run
            row = {'question': question, 'page': page, 'passed': False, 'error': f'{type(error).__name__}: {error}'[:200]}
        rows.append(row)
        mark = 'PASS' if row['passed'] else 'FAIL'
        print(f'[{mark}] {question}  {row.get("chars", 0)}字 {row.get("seconds", 0)}s {row.get("tools") or ""}'
              f'{"  缺：" + str(row.get("missing") or row.get("error")) if not row["passed"] else ""}', flush=True)
    passed = sum(1 for row in rows if row['passed'])
    out = Path('tmp') / 'bunny-eval'
    out.mkdir(parents=True, exist_ok=True)
    report = out / f'knowledge-{time.strftime("%Y%m%d-%H%M%S")}.json'
    report.write_text(json.dumps({'passed': passed, 'total': len(rows), 'rows': rows}, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    print(f'{passed} / {len(rows)} passed; report: {report}', flush=True)
    return 0 if rows and passed == len(rows) else 1


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    os._exit(code)
