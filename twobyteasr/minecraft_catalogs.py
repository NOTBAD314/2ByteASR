"""Known public source entry points, never a hard-coded Minecraft term list."""
from urllib.parse import quote

MANIFEST = 'https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'

SCOPES = (('mob','生物'),('block','方块'),('item','物品'),('enchantment','附魔'),
          ('status_effect','状态效果'),('dimension','维度'),('structure','结构'),('mechanic','游戏机制'))


def known_catalogs(game):
    if str(game).strip().casefold() not in {'我的世界','minecraft'}:
        return []
    return [dict(url='https://zh.minecraft.wiki/w/'+quote('Category:'+label),
        title='Category:'+label,covers=key,category_title=label,
        source_note='社区目录；实时抓取成功后才产生候选，Java/基岩/版本范围待核对') for key,label in SCOPES]


def official_catalog():
    return dict(url=MANIFEST, title='Minecraft Java 官方简体中文实体名称',
                covers='minecraft_assets', collector='minecraft_assets')


def translation_terms(payload):
    """Use exact registered entity keys, not menus/descriptions or invented names."""
    import re
    kinds = {'entity': ('entity', '实体'), 'block': ('block', '方块'),
             'item': ('item', '物品'), 'enchantment': ('enchantment', '附魔'),
             'effect': ('status_effect', '状态效果'), 'biome': ('biome', '群系')}
    for key, value in payload.items():
        match = re.fullmatch(r'(entity|block|item|enchantment|effect|biome)\.minecraft\.([a-z0-9_]+)', str(key))
        if (match and isinstance(value, str) and 1 <= len(value.strip()) <= 64
                and not re.search(r'[%{}§\r\n]', value)):
            kind, label = kinds[match[1]]
            # Entity registries also contain boats, projectiles and displays.
            # A corresponding spawn-egg entry is a structural living-mob cue;
            # the remainder stays explicitly broad, never all marked core mobs.
            if match[1]=='entity' and f'item.minecraft.{match[2]}_spawn_egg' in payload:
                kind,label='mob','生物'
            yield dict(term=value.strip(), category_key=kind, category=label, registry_key=key)


def fetch_official_terms(board, emit):
    """Bounded public JSON chain, content hashes verified before parsing terms.

    No client JAR, game binaries or model downloads. A fresh build checks latest;
    a completed checkpoint retains its explicitly recorded version/scope.
    """
    import hashlib
    import json
    import re
    import time
    from urllib.parse import urlsplit
    from . import network_policy
    from .provider_diagnostics import redact_diagnostics
    allowed = {'piston-meta.mojang.com', 'launchermeta.mojang.com', 'resources.download.minecraft.net'}

    def get_json(url, sha1=None, expected_size=None):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password:
            raise ValueError('官方资源目录返回了非授权主机')
        health = board.for_host(parsed.hostname)
        if health.in_cooldown():
            raise ValueError('source_cooldown:' + health.last_error)
        emit('资料抓取', f'请求官方公开 JSON：{url}')
        health.total_requests += 1
        size = 0
        chunks = []
        try:
            with network_policy.get(url, headers={'User-Agent': '2ByteASR/0.2.5 glossary'},
                                    timeout=board.request_timeout(), allow_redirects=False, stream=True) as response:
                status = response.status_code
                if status != 200:
                    kind = 'blocked' if status in {401, 403} else 'throttled' if status == 429 else f'http_{status}'
                    board.receipts.append(dict(url=url, status=status, fetched_at=time.time()))
                    raise ValueError(kind)
                for part in response.iter_content(65536):
                    if board.cancel_check:
                        board.cancel_check()
                    size += len(part)
                    if size > 8_000_000:
                        raise ValueError('官方 JSON 超过8MB边界')
                    chunks.append(part)
            raw = b''.join(chunks)
            actual = hashlib.sha1(raw).hexdigest()
            if sha1 and actual != sha1:
                raise ValueError('官方 JSON 内容哈希不匹配')
            if expected_size is not None and size != int(expected_size):
                raise ValueError('官方 JSON 长度不匹配')
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError('官方 JSON 不是对象')
            board.receipts.append(dict(url=url, status=200, body_bytes=size,
                body_sha256=hashlib.sha256(raw).hexdigest(), sha1_verified=bool(sha1), fetched_at=time.time()))
            health.record_success()
            return payload
        except Exception as exc:
            from .glossary_skill import GlossarySearchError
            if isinstance(exc, GlossarySearchError):
                raise
            health.record_failure(redact_diagnostics(str(exc))[:160])
            raise

    manifest = get_json(MANIFEST)
    version = str(manifest.get('latest', {}).get('release', ''))
    entry = next((v for v in manifest.get('versions', []) if v.get('id') == version and v.get('type') == 'release'), None)
    if not entry:
        raise ValueError('官方目录缺少正式版本')
    release = get_json(entry['url'], entry['sha1'])
    asset = release['assetIndex']
    index = get_json(asset['url'], asset['sha1'], asset.get('size'))
    language = index['objects']['minecraft/lang/zh_cn.json']
    digest = language['hash']
    if not re.fullmatch('[0-9a-f]{40}', digest):
        raise ValueError('官方语言资源哈希非法')
    language_url = f'https://resources.download.minecraft.net/{digest[:2]}/{digest}'
    terms = list(translation_terms(get_json(language_url, digest, language['size'])))
    if not terms:
        raise ValueError('官方语言资源未取得实体名称')
    return dict(terms=terms, version=version, url=language_url, release_url=entry['url'],
                scope=f'Java {version} 官方简体中文名称；不含模组/基岩差异/结构机制或社区别名',
                fetched_at=time.time(), asset_sha1=digest)
