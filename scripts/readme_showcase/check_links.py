"""Render Markdown with GitHub's GFM API and check relative links, images and anchors."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(sys.argv[1]).resolve()
FILES = sys.argv[2:]
OUT = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve() / 'work' / 'rendered'
OUT.mkdir(parents=True, exist_ok=True)


def render(path: Path) -> str:
    body = json.dumps(dict(text=path.read_text('utf8'), mode='markdown'))
    tmp = OUT / '_body.json'
    tmp.write_text(body, 'utf8')
    result = subprocess.run(['gh', 'api', '-X', 'POST', 'markdown', '--input', str(tmp)], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf8', 'replace') + result.stdout.decode('utf8', 'replace')[:400])
    return result.stdout.decode('utf8')


problems = []
report = {}
for rel in FILES:
    path = ROOT / rel
    text = path.read_text('utf8')
    rendered = render(path)
    (OUT / (rel.replace('/', '__') + '.html')).write_text(rendered, 'utf8')
    anchors = {unquote(a) for a in re.findall(r'id="user-content-([^"]+)"', rendered)}
    targets = re.findall(r'\]\(([^)\s]+)\)', text) + re.findall(r'(?:src|srcset|href)="([^"]+)"', text)
    checked = 0
    for target in targets:
        target = html.unescape(target)
        parsed = urlparse(target)
        if parsed.scheme in ('http', 'https', 'mailto'):
            continue
        checked += 1
        file_part, _, frag = target.partition('#')
        if file_part:
            dest = (path.parent / unquote(file_part)).resolve()
            if not dest.exists():
                problems.append(f'{rel}: missing {target}')
                continue
            if frag and dest.suffix == '.md':
                other = {unquote(a) for a in re.findall(r'id="user-content-([^"]+)"', render(dest))}
                if unquote(frag).lower() not in other:
                    problems.append(f'{rel}: missing anchor {target}')
        elif frag and unquote(frag).lower() not in anchors:
            problems.append(f'{rel}: missing in-page anchor #{frag}')
    images = re.findall(r'<img[^>]+src="([^"]+)"', rendered)
    report[rel] = dict(links_checked=checked, anchors=len(anchors), rendered_images=len(images),
                       external=sorted({t for t in targets if t.startswith('http')}))

print(json.dumps(report, ensure_ascii=False, indent=1))
print('PROBLEMS:', problems or 'none')
sys.exit(1 if problems else 0)
