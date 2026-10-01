"""Zero-credit ordinary Studio entry, backed by an explicitly local HTTP fixture.

This proves transport/authoring/preview/adoption persistence, not model quality.
The existing normal-entry audit still requires inspected pixels before adoption.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-frame',type=Path);parser.add_argument('--exe',type=Path)
    parser.add_argument('--ice-fixture',action='store_true',help='Use this round Codex-authored ice component; no external model')
    parser.add_argument('--noita-fixture',action='store_true',help='Exercise Noita v8 through local HTTP and normal adoption')
    parser.add_argument('--resume-ledger',type=Path);parser.add_argument('--retry-saved-candidate');args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('Use a fresh repository tmp directory')
    setup=out.parent/(out.name+'-setup');setup.mkdir(exist_ok=True)
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            data=json.dumps({'object':'list','data':[{'id':'local-caption-fixture','object':'model'}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            from twobyteasr.source_artifact import frame,token
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            parts=[]
            for message in payload['messages']:
                content=message['content']
                parts.append(content if isinstance(content,str) else '\n'.join(p.get('text','') for p in content))
            prompt='\n'.join(parts);markers=re.findall(r'2BYTE-ARTWORK/1 ([a-f0-9]{24})',prompt)
            if markers:
                text=frame(dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':{
                    'version':8 if args.noita_fixture else 6 if args.ice_fixture else 2,
                    'emphasis':['药剂'] if args.noita_fixture else ['自动战斗']}})),'fixture').replace(token('fixture'),markers[-1])
                kind='source_artifact'
            else:
                text=json.dumps({'candidates':[{'name':'冰河世纪 · 霜脊冰刻' if args.ice_fixture else '秩序 · 双线压印','design':'厚冰层和内部切面，实心冰刻字、霜边和裂纹；结晶入场，持续冷光，裂散退出。' if args.ice_fixture else '黑白明暗组织文字，暖灰双细线与自适应薄底板，重点词套色对齐、字组落位后有序收回。'}]},ensure_ascii=False)
                kind='direction'
                if args.noita_fixture:
                    text=json.dumps({'candidates':[{'name':'Noita · 炼金反应铭牌','design':'原创药瓶承托暗石铭牌，暖白实心像素字与药剂绿关键词，法印点亮召唤、阅读时局部反应、阶梯回收。'}]},ensure_ascii=False)
            calls.append(dict(kind=kind,at=time.time(),model=payload.get('model'),bytes=len(prompt.encode()),external_model_call=False))
            (setup/'local-http-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),'utf8')
            self.send_response(200)
            if payload.get('stream'):
                self.send_header('Content-Type','text/event-stream');self.end_headers()
                for i in range(0,len(text),160):
                    event={'id':'fixture','choices':[{'index':0,'delta':{'content':text[i:i+160]},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
                self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
            else:
                data=json.dumps({'id':'fixture','choices':[{'message':{'role':'assistant','content':text},'finish_reason':'stop'}]}).encode()
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    import os
    os.environ['TWOBYTEASR_TEST_ROOT']=str(setup)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.settings import DEFAULT_SETTINGS
    from twobyteasr.llm_config import activate_ai_service,update_active_profile,save_api_key_for
    import copy
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'custom')
    address=f'http://127.0.0.1:{server.server_port}/v1'
    update_active_profile(settings,base_url=address,model='local-caption-fixture')
    save_api_key_for('custom',address,'local-fixture-only')
    config=setup/'settings.json';config.write_text(json.dumps(settings,ensure_ascii=False),'utf8')
    sys.argv=['verify_normal_ai_entry.py','--output',str(out),'--settings',str(config),'--service','custom',
        '--model','local-caption-fixture','--expected-candidates','1','--isolated-desktop','--local-fixture',
        '--cue-text','这块石头这么圆 一定能推吧？' if args.ice_fixture else '这种就属于是点了自动战斗',
        '--prompt','冰河世纪主题，厚冰块材质与结晶进退场，默认纯字幕预览。' if args.ice_fixture else 'chess对弈：抽象、文字优先，细边与薄底板。',
        '--cue-seconds','3','--timeout','900']
    if args.exe:sys.argv+=['--exe',str(args.exe)]
    if args.noita_fixture:
        sys.argv[sys.argv.index('--cue-text')+1]='这瓶药剂，真的能喝吗？'
        sys.argv[sys.argv.index('--prompt')+1]='Noita 炼金像素字幕，使用原创炼金反应铭牌，实心像素汉字，避免之前冰主题的透明字和昂贵滤镜。'
        sys.argv[sys.argv.index('--cue-seconds')+1]='6'
        sys.argv+=['--replacement-text','法杖还剩 100 Mana，别乱喝！','--verify-restore','--wait-web-proxy']
    if args.resume_ledger:sys.argv+=['--resume-ledger',str(args.resume_ledger)]
    if args.retry_saved_candidate:sys.argv+=['--retry-saved-candidate',args.retry_saved_candidate]
    sys.argv+=['--game-frame',str(args.game_frame)] if args.game_frame else ['--game-scene']
    try:
        from verify_normal_ai_entry import main as verify
        return verify()
    finally:server.shutdown()


if __name__=='__main__':raise SystemExit(main())
