"""Bounded public reference discovery before ideation; no user text/media sent.

Search snippets are quoted evidence, never instructions or claimed image review.
Known published samples remain an explicitly labelled offline fallback.
"""
import hashlib
import json
import re
import time
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree

VERSION='caption-reference-search-5'


def is_zelda(prompt):
    return bool(re.search('塞尔达|赛尔达|薩爾達|zelda',prompt,re.I))


def queries_for(prompt):
    if is_zelda(prompt):
        return ['Nintendo Zelda Tears of the Kingdom official visual design']
    from .caption_noita import is_noita
    if is_noita(prompt):
        return ['Noita official screenshots alchemy wands spells UI', 'Noita wand inventory potion pixel magic']
    from .caption_style_reference import is_balatro
    from .caption_reference_catalog import is_ice
    if is_ice(prompt):
        return ['animated captions kinetic typography open source projects', 'ice frost text effect SVG blend material animation']
    if is_balatro(prompt):
        return ['Balatro press kit game UI animation', 'Boris FX Damaged TV Dissolve split video transition plugins']
    if re.search(r'CRT|扫描|像素|glitch|noise|foil|neon|霓虹|振动|翻倍|杂色|动态字|字效',prompt,re.I):
        return ['Boris FX Damaged TV Dissolve split video transition plugins']
    return ['animated captions kinetic typography open source projects']


def _download(url, timeout):
    import requests
    from .network_policy import ca_bundle
    verify,_=ca_bundle()
    # No arbitrary result URL fetching, automatic redirect, or script execution.
    with requests.get(url,timeout=(min(timeout,3),min(timeout,3)),verify=verify,
                      allow_redirects=False,stream=True,headers={'User-Agent':'2ByteASR-Reference/1'}) as response:
        response.raise_for_status()
        if response.status_code!=200:raise ValueError('公开来源没有返回正文')
        chunks=[];size=0;deadline=time.monotonic()+timeout
        for chunk in response.iter_content(16384):
            if time.monotonic()>deadline:raise TimeoutError('参考读取达到时限')
            size+=len(chunk)
            if size>350000:raise ValueError('参考正文超过取样上限')
            chunks.append(chunk)
        return b''.join(chunks)


def search_references(ledger, *, progress=lambda _:None, cancel_check=lambda:False, fetch=_download):
    queries=queries_for(ledger.value['raw_user_prompt'])
    if not queries:return None
    if ledger.value.get('reference_search'):
        progress('复用本任务已保存的参考与提炼')
        return ledger.value['reference_search']
    folder=ledger.root/'reference-search';folder.mkdir(exist_ok=True)
    start=time.monotonic();deadline=start+14
    result=dict(version=VERSION,provider='Bing public RSS + official page',started_at=time.time(),
                queries=queries,sources=[],attempts=[],errors=[],new_web_search_this_request=False,
                pixels_seen=False,user_text_sent=False,model_calls=0)
    for index,query in enumerate(queries):
        if cancel_check():raise InterruptedError('参考搜索已取消')
        remaining=deadline-time.monotonic()
        if remaining<=.1:break
        progress('搜索字幕项目与材质案例 · '+query)
        url='https://www.bing.com/search?'+urlencode({'q':query,'format':'rss'})
        attempt=dict(query=query,url=url,status='failed');result['attempts'].append(attempt)
        try:
            body=fetch(url,min(4,remaining));(folder/f'search-{index}.xml').write_bytes(body)
            if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('不接受XML外部实体')
            tree=ElementTree.fromstring(body)
            if tree.tag!='rss':raise ValueError('搜索返回非RSS正文')
            rows=[]
            for item in tree.findall('./channel/item')[:5]:
                link=item.findtext('link','');parsed=urlparse(link)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username:continue
                relevance=' '.join([item.findtext('title',''),item.findtext('description',''),link])
                pattern=(r'noita|nolla' if query.startswith('Noita') else
                         r'zelda|ゼルダ|nintendo' if query.startswith('Nintendo') else
                         r'balatro|小丑牌' if query.startswith('Balatro') else
                         r'boris|transition|dissolve|转场|插件|scanline' if query.startswith('Boris') else
                         r'ice|frost|svg|冰|霜|blend' if query.startswith('ice') else
                         r'caption|typograph|text.?effect|字幕|字效|codrops|textillate')
                if not re.search(pattern,relevance,re.I):continue
                rows.append(dict(title=item.findtext('title','')[:160],url=link,
                    excerpt=re.sub('<[^>]+>',' ',item.findtext('description',''))[:400],kind='search_excerpt'))
            if not rows:raise ValueError('搜索没有可用来源')
            result['sources'].extend(rows);attempt.update(status='complete',count=len(rows),sha256=hashlib.sha256(body).hexdigest())
            result['new_web_search_this_request']=True
        except Exception as exc:
            attempt['error']=type(exc).__name__;result['errors'].append(type(exc).__name__)
    from .caption_style_reference import is_balatro
    from .caption_noita import is_noita
    noita_request=is_noita(ledger.value['raw_user_prompt'])
    zelda_request=is_zelda(ledger.value['raw_user_prompt'])
    if zelda_request and deadline-time.monotonic()>.1:
        url='https://www.nintendo.com/jp/zelda/totk/index.html'
        try:
            body=fetch(url,min(4,deadline-time.monotonic()))
            if b'zelda' not in body.lower():raise ValueError('官方正文缺少预期信息')
            (folder/'zelda-official.html').write_bytes(body)
            result['sources'].append(dict(title='Nintendo Tears of the Kingdom',url=url,kind='page_verified',
                sha256=hashlib.sha256(body).hexdigest(),excerpt='王国之泪官方页面；本次正文读取不代表本次模型看图。'))
        except Exception as exc:result['errors'].append('zelda_official:'+type(exc).__name__)
    if noita_request and deadline-time.monotonic()>.1:
        try:
            body=fetch('https://noitagame.com/',min(4,deadline-time.monotonic()))
            if b'Noita' not in body or b'pixel' not in body:raise ValueError('Noita官方正文缺少预期信息')
            (folder/'noita-official.html').write_bytes(body)
            result['sources'].append(dict(title='Noita official',url='https://noitagame.com/',kind='page_verified',
                sha256=hashlib.sha256(body).hexdigest(),excerpt='官方说明像素材料模拟、自制法术、矿洞等环境；本次正文读取不代表模型看过截图。'))
        except Exception as exc:result['errors'].append('noita_official:'+type(exc).__name__)
    if is_balatro(ledger.value['raw_user_prompt']) and deadline-time.monotonic()>.1:
        try:
            body=fetch('https://www.playbalatro.com/press-kit/',min(4,deadline-time.monotonic()))
            if b'Balatro' not in body or b'Jokers' not in body:raise ValueError('官方页面未含预期素材目录')
            (folder/'official-page.html').write_bytes(body)
            result['sources'].append(dict(title='Balatro Press Kit',url='https://www.playbalatro.com/press-kit/',
                kind='page_verified',sha256=hashlib.sha256(body).hexdigest(),
                excerpt='官方目录含 Jokers、Hand Levels、Decks、Combo、游戏UI与GIF。目录验证不代表本次看过全部图片。'))
        except Exception as exc:result['errors'].append('official_page:'+type(exc).__name__)
    from .caption_reference_catalog import is_ice,PROJECTS,TRANSLATION,HYPERFRAMES_REFERENCES,HYPERFRAMES_COMMIT
    material_request=not noita_request and (is_ice(ledger.value['raw_user_prompt']) or queries[0].startswith('animated'))
    if material_request and deadline-time.monotonic()>.1:
        url='https://raw.githubusercontent.com/codrops/KineticTypePageTransition/main/README.md'
        try:
            body=fetch(url,min(4,deadline-time.monotonic()))
            if b'Kinetic Typography' not in body:raise ValueError('项目正文未含预期标题')
            (folder/'caption-project.md').write_bytes(body)
            result['sources'].append(dict(title='Codrops Kinetic Typography Page Transition',url=PROJECTS[1]['url'],
                kind='page_verified',sha256=hashlib.sha256(body).hexdigest(),excerpt='作者项目说明：背景字进入前景并显露内容层。仅正文核验，不冒充本次观看演示。'))
        except Exception as exc:result['errors'].append('caption_project:'+type(exc).__name__)
    if not material_request and not noita_request and not zelda_request and deadline-time.monotonic()>.1:
        try:
            body=fetch('https://docs.libretro.com/shader/crt/',min(4,deadline-time.monotonic()))
            if b'phosphor' not in body or b'scanline' not in body:raise ValueError('CRT来源未含预期内容')
            (folder/'crt-source.html').write_bytes(body)
            result['sources'].append(dict(title='Libretro CRT Shaders',url='https://docs.libretro.com/shader/crt/',
                kind='page_verified',sha256=hashlib.sha256(body).hexdigest(),
                excerpt='扫描线、磷光遮罩、局部辉光与缩放混叠需要分别控制；仅提取字面材料思路，不复制整屏滤镜。'))
        except Exception as exc:result['errors'].append('crt_page:'+type(exc).__name__)
    result['status']='searched' if result['new_web_search_this_request'] else 'published_pages_only' if result['sources'] else 'cached_reference_only'
    result['elapsed_seconds']=round(time.monotonic()-start,3)
    result['translation']=[
        '字面：保留清晰中文骨架，CRT用持续缓慢扫描/磷光细纹，像素噪点低对比地持续流动；正文不大幅震动。',
        '关键词：红mult与蓝chips做触发层级；短促翻出/回弹后保留克制微动；紫稀有度与foil低频循环反光。',
        '边界：沿用效果说明窗、厚轮廓/凹槽/封签，避免把卡牌角色图当字幕装饰。',
        '动作：借鉴视频转场插件的信号失锁/恢复、冲击回弹、分割遮罩与双向收束；缩到字幕框内，先框再正文再标签，退出分层回收。不是查剪辑软件菜单内置特效。']
    result['curated_motion_references']=[
        dict(title='BCC Damaged TV Dissolve',url='https://borisfx.com/documentation/continuum/bcc-damaged-tv-dissolve/',kind='bundled_author_reviewed_documentation',observation='滚屏、静电、干扰线与色差分组，过渡时间与强度独立控制；转译为字幕通电锁定和压线熄灭。'),
        dict(title='Split Transitions Pack',url='https://www.lookae.com/split-transitions-2/',kind='bundled_author_reviewed_catalog',observation='画面分割拆分转场；作者转译为底板与封套相反方向遮罩开合。未宣称观看插件演示。'),
        dict(title='Lightspeed Transitions V2',url='https://www.lookae.com/lightspeed-transitions-v2/',kind='bundled_author_reviewed_catalog',observation='流畅运动、遮罩高光、缩放/方向模糊等可组合控制；字幕采用短冲击与回弹，不给正文添加全屏模糊。')]
    result['translation_basis']='随包已审阅图像与作者设计转译；联网摘要只作补充资料，不是已看图回执'
    if material_request:
        result['translation']=TRANSLATION
        result['curated_motion_references']=[dict(row,kind='bundled_author_read_project') for row in PROJECTS]
        result['translation_basis']='2026-09-25作者在线项目检索与源码/README阅读的转译；本次搜索/读取状态独立记录，未声称观看外部动画。'
    if not noita_request and is_ice(ledger.value['raw_user_prompt']):
        result['curated_motion_references']=[dict(row,kind='bundled_author_read_source') for row in HYPERFRAMES_REFERENCES]
        result['translation_basis']='2026-09-26作者读取固定HyperFrames提交'+HYPERFRAMES_COMMIT+'的四条真实实现；CLI0.8.77独立安装通过。没有导入来源待确认贴图，没有声称本次请求再次联网读取这些源码。'
    if noita_request:
        result['translation']=['暗土褐/煤灰阅读面、实心暖白字，局部旧金刻符/药剂绿/余烬橙；原创阶梯磨损而非复制官方资源。',
            '法印点亮召唤、正文稳定局部反应、阶梯回收；不套CRT、恐怖血字或JRPG对话框。']
        result['curated_motion_references']=[
            dict(title='Noita Holy Mountain screenshot',url='https://noitagame.com/screenshots/screenshot_013.jpg',kind='author_viewed_reference_20260926',observation='暗石层次、金刻符、局部蓝绿法光；仅供视觉转译，素材不进入主题。'),
            dict(title='Noita alchemical cave screenshot',url='https://noitagame.com/screenshots/screenshot_010.jpg',kind='author_viewed_reference_20260926',observation='多色细小药瓶、岩层、离散火花与熔岩；不将场景搬进字幕。'),
            dict(title='Noita wand interface reference',url='https://noita.wiki.gg/wiki/Wands',kind='author_viewed_reference_20260926',observation='黑底信息优先、像素字、细小物件与有限旧金框。')]
        result['translation_basis']='2026-09-26作者实际浏览官方截图和法杖说明图后的原创转译；当前模型未因此自动看到像素。'
    if zelda_request:
        result['translation']=['若用户未指定作品，选择王国之泪：青绿断环、密集回旋刻纹、奶油白磨损字标与石构明暗关系。纹样嵌入框形和动作，不靠绿金配色或贴图标冒充主题。',
            '文字主导；默认不画角色。轮廓与局部能量可有清楚节奏；入场/阅读/退场按主题事件设计，不套CRT/卡牌动作。']
        result['curated_motion_references']=[]
        result['translation_basis']='2026-09-27作者浏览官方主页并实际查看动画背景、青绿断环字标；观察文字供模型参考，不代表当前模型收到图片。'
    elif not noita_request and not material_request and not is_balatro(ledger.value['raw_user_prompt']) and not re.search(r'CRT|扫描|glitch',ledger.value['raw_user_prompt'],re.I):
        result['translation']=[]
        result['curated_motion_references']=[]
    ledger.value['reference_search']=result
    (folder/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8');ledger.save()
    progress(('参考搜索完成' if result['new_web_search_this_request'] else '搜索无相关结果，已读取公开参考页' if result['sources'] else '在线参考暂不可用，使用随包已审阅参考')+' · 提炼字面、材料与主题动作')
    return result


def prompt_evidence(ledger):
    value=ledger.value.get('reference_search')
    if not value:return None
    result={key:value[key] for key in ('status','provider','new_web_search_this_request','pixels_seen','translation','translation_basis') if key in value}
    # Old searches are retained as receipts, but their cross-theme art advice
    # cannot become current instructions when resuming a saved direction.
    if value.get('version')!=VERSION:
        result.pop('translation',None);result.pop('translation_basis',None)
    result['sources']=[dict(row,excerpt=row.get('excerpt','')[:160]) for row in value['sources'][:6]]
    result['project_adaptations']=value.get('curated_motion_references',[])[:4] if value.get('version')==VERSION else []
    return result
