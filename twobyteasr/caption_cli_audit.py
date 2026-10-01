"""Explicit, single real Codex request using only synthetic subtitle text."""
import json
import os
from pathlib import Path
import time
import traceback


def main(output):
    out = Path(output).resolve()
    if not out.is_relative_to(Path.cwd()/'tmp'):
        raise ValueError('audit output must be inside repository tmp')
    out.mkdir(parents=True, exist_ok=True)
    from .codex_cli_provider import CodexCLIProvider
    provider = CodexCLIProvider()
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'),
                      TEMP=str(out), TMP=str(out), QT_QPA_PLATFORM='offscreen')
    from .build_identity import load_build_identity
    from .web_theme import WebThemeDocument
    from .provider_diagnostics import redact_diagnostics
    string = {'type': 'string'}
    schema = {'type':'object','additionalProperties':False,'required':['name','palette','appearance','cueHtml','cueCss'],
              'properties':{'name':string, 'palette':{'type':'object','additionalProperties':False,
                  'required':['primary','text'],'properties':{'primary':string,'text':string}},
                  'appearance':{'type':'object','additionalProperties':False,'required':['fontFamily','fontSize','color'],
                    'properties':{'fontFamily':string,'fontSize':{'type':'number'},'color':string}},
                  'cueHtml':string,'cueCss':string}}
    result = {'identity':load_build_identity().to_dict(), 'real_requests':0, 'passed':False}
    started=time.perf_counter()
    try:
        result['status']=provider.validate(timeout=10,use_cache=False).message
        result['real_requests']=1
        generated=provider.structured_complete([{'role':'user','content':
            '生成一份最小中文字幕主题。只使用合成测试文案“字幕测试”，cueHtml 使用 {{text}} 占位符。'
            '单行、白字、Source Han Sans SC 字体58px，位于1920x1080舞台底部。'
            '技术契约必须满足：正文 CSS 的字体必须使用 font-family:var(--wt-font);font-size:var(--wt-size)。'
            '仅简单 div/span 和静态 CSS，无外链、无脚本、无动画。palette.primary 和 text 使用 #FFFFFF。'
            'appearance 必须是对象，fontFamily 为 Source Han Sans SC，fontSize 为58，color 为 #FFFFFF。'}],
            schema,timeout=89)
        (out/'generated.json').write_text(json.dumps(generated,ensure_ascii=False,indent=2),encoding='utf8')
        theme=WebThemeDocument.from_dict(generated).to_dict()
        (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),encoding='utf8')
        result['passed']=True
    except Exception as exc:
        result.update(error=redact_diagnostics(str(exc)),category=getattr(exc,'category','validation'),
                      traceback=redact_diagnostics(traceback.format_exc()))
    result['elapsed_seconds']=time.perf_counter()-started
    result['trace']=redact_diagnostics(provider.last_invocation_trace)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','elapsed_seconds','category','error','real_requests')},ensure_ascii=False))
    return 0 if result['passed'] else 1
