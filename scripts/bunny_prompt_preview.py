"""Print what 「问问兔白」 would send to the text AI for one question (2026-11-14).

Use it to read the persona and world book, or paste the output into any chat AI to try how
兔白 talks before the in-app chat exists. Nothing is sent anywhere.

    python -X utf8 scripts/bunny_prompt_preview.py "怎么加标点"
    python -X utf8 scripts/bunny_prompt_preview.py --page 首页 --no-ai "我没有显卡可以用吗"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.app import bunny_lore, bunny_persona  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('question')
    parser.add_argument('--page', default='首页')
    parser.add_argument('--no-ai', action='store_true', help='show the answer without a text AI instead')
    args = parser.parse_args(argv)
    if args.no_ai:
        from twobyteasr.app.feature_search import entries
        print(bunny_persona.offline_reply(args.question, entries(object())))
        return 0
    lore = bunny_lore.build_entries()
    messages = bunny_persona.build_messages(
        args.question, features=bunny_lore.feature_index(), core=bunny_lore.CORE,
        entries=bunny_lore.select(args.question, lore), state={'page': args.page})
    for message in messages:
        print(f'===== {message["role"]} =====')
        print(message['content'])
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
