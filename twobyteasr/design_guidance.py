"""Versioned, packaged art skills consumed by both normal authoring routes."""
import hashlib
from pathlib import Path
from functools import lru_cache

VERSION = 'theme-identity-20260927.2'


@lru_cache(maxsize=16)
def _document(path,mtime,size):
    return Path(path).read_bytes()


def load_design_guidance(raw_prompt, *, root=None):
    if root is None:
        from .runtime_paths import detect_install_root
        root = detect_install_root()
    directory = Path(root) / 'assets/design-skills'
    names = ['abstract-caption.md']
    text = str(raw_prompt).casefold()
    if any(word in text for word in ('材质','冰','火','金属','木刻','crt','玻璃','foil','metal','frost','ice')):
        names.append('material-caption.md')
    theme = 'user-defined'
    from .caption_style_reference import is_balatro
    from .caption_noita import is_noita
    if is_noita(raw_prompt):
        theme = 'Noita'
        names.append('noita-caption.md')
    elif is_balatro(raw_prompt):
        theme = 'Balatro'
        names.append('balatro-caption.md')
    elif any(word in text for word in ('塞尔达', '赛尔达', '薩爾達', 'zelda')):
        theme = 'Zelda'
        names.append('zelda-caption.md')
    elif any(word in text for word in ('初音', 'miku', 'hatsune')):
        theme = 'Miku'
    elif any(word in text for word in ('minecraft', '我的世界')):
        theme = 'Minecraft'
    contents, receipts = [], []
    for name in names:
        path=directory/name;stat=path.stat()
        data = _document(str(path),stat.st_mtime_ns,stat.st_size)
        document=data.decode('utf8')
        # Skill routing belongs to the host, not to the completion model.
        if document.startswith('---\n'):document=document.split('---\n',2)[-1]
        document=document.split('# 产品调用路径',1)[0].strip()
        contents.append(document)
        receipts.append({'path':'assets/design-skills/'+name,
                         'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)})
    return '\n\n'.join(contents), {'version':VERSION, 'theme':theme, 'files':receipts}
