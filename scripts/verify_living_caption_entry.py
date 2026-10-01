"""Actual Studio recovery against a loopback fault supplier, no external credits."""
import argparse
import copy
import json
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--fault',choices=('zero','half','motion','twice'),default='zero')
    parser.add_argument('--game-frame',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('Use fresh tmp output')
    setup=out.parent/(out.name+'-setup');setup.mkdir(exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(setup)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.caption_living_motion import examples,compose
    from twobyteasr.web_theme import WebThemeDocument
    from twobyteasr.source_artifact import frame,from_theme,token,unframe
    theme=WebThemeDocument.from_dict(dict(name='CRT · 通电提示',**compose(dict(examples()[0],emphasis=['自动战斗'])))).to_dict()
    calls=[];original=[None];cut=[None];implementations=[0]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            data=json.dumps({'object':'list','data':[{'id':'local-caption-fixture','object':'model'}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            prompt='\n'.join(m['content'] if isinstance(m['content'],str) else '\n'.join(p.get('text','') for p in m['content']) for m in payload['messages'])
            matches=re.findall(r'(2BYTE-(?:ARTWORK|COMPLETION|CONTINUATION)/1) ([a-f0-9]{24})',prompt)
            finish='stop'
            if not matches:
                text=json.dumps({'candidates':[{'name':'CRT · 通电提示','design':'青绿电子屏，紫稀有封签，扫描持续贯穿阅读期，字框轻微浮动；扫描线展开通电，标签后锁，文字失活后屏幕收线熄灭。'}]},ensure_ascii=False);kind='direction'
            else:
                protocol,marker=matches[-1];implementations[0]+=1
                if implementations[0]==1 or args.fault=='twice' and implementations[0]==2:
                    original[0]=from_theme(theme,'fixture').replace(token('fixture'),marker)
                    cut[0]=original[0].index('bui-stock')+5
                    if args.fault in {'zero','twice'}:text='';finish='length'
                    elif args.fault=='half':text=original[0][:cut[0]];finish='length'
                    else:
                        parts,_=unframe(from_theme(theme,'fixture'),'fixture')
                        text=frame(dict(parts,PARAMETERS='{}'),'fixture').replace(token('fixture'),marker)
                    kind='injected_'+args.fault
                else:
                    if protocol=='2BYTE-CONTINUATION/1':text=frame({'TAIL':original[0][cut[0]:]},'fixture',kind=protocol).replace(token('fixture'),marker)
                    elif protocol=='2BYTE-COMPLETION/1':text=frame({'PARAMETERS':json.dumps({k:theme[k] for k in ('motionSpec','palette','appearance')})},'fixture',kind=protocol).replace(token('fixture'),marker)
                    else:text=from_theme(theme,'fixture').replace(token('fixture'),marker)
                    kind='recovered_implementation'
            calls.append(dict(kind=kind,at=time.time(),model=payload.get('model'),prompt_bytes=len(prompt.encode()),external_model_call=False,finish_reason=finish))
            (setup/'local-http-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),'utf8')
            self.send_response(200)
            if payload.get('stream'):
                self.send_header('Content-Type','text/event-stream');self.end_headers()
                for i in range(0,len(text),160):
                    event={'id':'local-fault','choices':[{'index':0,'delta':{'content':text[i:i+160]},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
                self.wfile.write(('data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
            else:
                data=json.dumps({'id':'local-fault','choices':[{'message':{'role':'assistant','content':text},'finish_reason':finish}]}).encode()
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    from twobyteasr.settings import DEFAULT_SETTINGS
    from twobyteasr.llm_config import activate_ai_service,update_active_profile,save_api_key_for
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'custom')
    address=f'http://127.0.0.1:{server.server_port}/v1';update_active_profile(settings,base_url=address,model='local-caption-fixture')
    save_api_key_for('custom',address,'local-fixture-only')
    config=setup/'settings.json';config.write_text(json.dumps(settings,ensure_ascii=False),'utf8')
    sys.argv=['verify_normal_ai_entry.py','--output',str(out),'--settings',str(config),'--service','custom',
        '--model','local-caption-fixture','--expected-candidates','1','--isolated-desktop','--local-fixture',
        '--cue-text','这种就属于是点了自动战斗','--prompt','CRT游戏提示框：持续扫描、颗粒、局部wiggle。通电、锁定、收线熄灭。',
        '--cue-seconds','3','--timeout','900']
    if args.exe:sys.argv+=['--exe',str(args.exe)]
    if args.fault=='twice':sys.argv+=['--recover-candidate','A']
    if args.fault=='motion':sys.argv+=['--rebuild-preview']
    sys.argv+=['--game-frame',str(args.game_frame)] if args.game_frame else ['--game-scene']
    try:
        from verify_normal_ai_entry import main as verify
        result=verify()
        expected=['direction']+['injected_'+args.fault]*(2 if args.fault=='twice' else 1)+['recovered_implementation']
        if [c['kind'] for c in calls]!=expected:
            raise AssertionError('Expected exactly direction + fault + one recovery')
        return result
    finally:server.shutdown()


if __name__=='__main__':raise SystemExit(main())
