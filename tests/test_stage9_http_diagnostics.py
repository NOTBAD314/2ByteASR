"""Short local HTTP fault matrix, never a cloud request or CLI launch."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from twobyteasr.providers.asr_http_transport import complete
from twobyteasr.providers.llm_adapter import LLMRequestError


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            code=int(self.path[1:]) if self.path[1:].isdigit() else 200
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('x-request-id','bounded-test-123')
            self.end_headers()
            try:
                if self.path=='/idle':
                    self.wfile.write(b'{');self.wfile.flush();time.sleep(.3)
                elif self.path in ('/total','/cancel'):
                    for _ in range(100):
                        self.wfile.write(b' ');self.wfile.flush();time.sleep(.01)
                elif self.path=='/empty':
                    pass
                elif self.path=='/invalid':
                    self.wfile.write(b'not-json')
                elif self.path=='/shape':
                    self.wfile.write(b'{}')
                else:
                    self.wfile.write(json.dumps({'model':'returned-model-id','choices':[{'message':{'content':'{"boundaries":[4]}'},'finish_reason':'stop'}]}).encode())
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown();server.server_close();worker.join(1)


@pytest.mark.parametrize('path,category',[('/429','rate_limited'),('/503','server_error'),('/idle','read_idle_timeout'),
    ('/total','total_timeout'),('/empty','empty_response'),('/invalid','parse_failure'),('/shape','format_mismatch')])
def test_http_faults_have_precise_categories_and_safe_metadata(server,path,category):
    diag={}
    with pytest.raises(LLMRequestError) as error:
        complete([],model='fixture',api_key='secret-test',url=server+path,max_tokens=10,
            timeout=(.1,.05 if path=='/idle' else .2),request_diagnostics=diag,
            _total_deadline=time.monotonic()+(.08 if path=='/total' else 1))
    assert error.value.category==category
    assert diag.get('http_request_id')=='bounded-test-123'
    assert 'secret-test' not in json.dumps(diag)
    assert 'Authorization' not in json.dumps(diag)


def test_http_cancel_and_first_activity(server):
    cancel=threading.Event()
    timer=threading.Timer(.05,cancel.set);timer.start()
    diag={}
    with pytest.raises(LLMRequestError) as error:
        complete([],model='fixture',api_key='secret',url=server+'/cancel',max_tokens=10,
                 timeout=(.1,.2),request_diagnostics=diag,cancel_check=cancel.is_set,
                 _total_deadline=time.monotonic()+1)
    timer.join()
    assert error.value.category=='cancelled'
    assert diag['first_activity_ms'] >= 0


def test_connect_timeout_is_distinct(monkeypatch):
    import requests
    monkeypatch.setattr(requests,'post',lambda *a,**k: (_ for _ in ()).throw(requests.ConnectTimeout('fixture')))
    with pytest.raises(LLMRequestError) as error:
        complete([],model='fixture',api_key='secret',url='http://127.0.0.1:1',max_tokens=10,request_diagnostics={})
    assert error.value.category=='connect_timeout'


def test_returned_model_is_recorded_separately_from_requested_model(server):
    diag={}
    complete([],model='requested-model-id',api_key='secret',url=server+'/ok',max_tokens=10,
             request_diagnostics=diag)
    assert diag['response_model']=='returned-model-id'
    assert 'secret' not in json.dumps(diag)


def test_response_close_error_cannot_leave_completion_waiting(monkeypatch):
    import requests
    class Response:
        status_code=200
        headers={}
        def iter_content(self,chunk_size):
            yield b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        def close(self):raise OSError('fixture close failed')
    monkeypatch.setattr(requests,'post',lambda *a,**k:Response())
    started=time.monotonic();diag={}
    assert complete([],model='fixture',api_key='fixture',url='http://127.0.0.1:1',max_tokens=10,
        timeout=2,request_diagnostics=diag)=='ok'
    assert time.monotonic()-started<.5
    assert diag['transport_cleanup_error']=='OSError'


@pytest.mark.parametrize('content,category',[('', 'structured_output_truncated_before_answer'),('{}','structured_output_truncated')])
def test_truncation_keeps_batch_split_category_without_transport_retry(monkeypatch,content,category):
    import requests
    calls=[]
    class Response:
        status_code=200
        headers={}
        def iter_content(self,chunk_size):
            yield json.dumps({'choices':[{'message':{'content':content},'finish_reason':'length'}]}).encode()
        def close(self):pass
    def post(*a,**k):calls.append(k);return Response()
    monkeypatch.setattr(requests,'post',post)
    with pytest.raises(LLMRequestError) as error:
        complete([],model='fixture',api_key='fixture',url='http://127.0.0.1:1',max_tokens=10,request_diagnostics={})
    assert error.value.category==category and len(calls)==1


def test_cli_exit_diagnostic_uses_owned_process_without_launch(monkeypatch):
    import io
    from types import SimpleNamespace
    from twobyteasr.providers import ai_providers
    from twobyteasr.providers.asr_provider_snapshot import classify_request_error
    process=SimpleNamespace(pid=1234,returncode=3,stdout=io.StringIO(''),stderr=io.StringIO('fixture exit'),poll=lambda:3)
    monkeypatch.setattr(ai_providers,'popen_hidden_subprocess',lambda *a,**k:process)
    provider=ai_providers.CLIProvider(model='fixture',executable='never-launched')
    monkeypatch.setattr(provider,'_request_command',lambda *a,**k:['never-launched'])
    diag={}
    with pytest.raises(ai_providers.AIProviderError) as error:
        provider.complete([],request_diagnostics=diag)
    assert classify_request_error(error.value)=='cli_exit'
    assert diag['cli_pid']==1234 and diag['cli_exit_code']==3


def test_bailian_search_uses_official_source_metadata_without_changing_host_or_model(monkeypatch):
    import requests
    calls=[]
    class Response:
        status_code=200
        headers={}
        def iter_content(self,chunk_size):
            yield json.dumps({'output':{'choices':[{'message':{'content':'{"mappings":[]}'},'finish_reason':'stop'}],
                'search_info':{'search_results':[{'url':'https://example.org/official'}]}},
                'usage':{'input_tokens':12,'output_tokens':4}}).encode()
        def close(self):pass
    def post(url,**kwargs):calls.append((url,kwargs['json']));return Response()
    monkeypatch.setattr(requests,'post',post)
    messages=[{'role':'user','content':'完整合成正文'}];diag={}
    assert complete(messages,model='qwen-plus',api_key='fixture',provider='bailian',
        url='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',max_tokens=4096,
        extra_body={'enable_search':True},request_diagnostics=diag)=='{"mappings":[]}'
    url,body=calls[0]
    assert url=='https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
    assert body['model']=='qwen-plus' and body['input']['messages']==messages
    assert body['parameters']['search_options']['enable_source'] is True
    assert diag['search_evidence'][0]['urls']==['https://example.org/official']
    assert diag['reported_usage']==[{'input_tokens':12,'output_tokens':4}]
