"""Controlled HTTP regressions; no external network or developer models."""
import hashlib
import importlib.util
import json
import threading
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from twobyteasr import repository_download as repo
from twobyteasr.download_diagnostics import redact
from twobyteasr.model_download_diagnostic import bounded_probe


@pytest.fixture
def client():
    path=Path(__file__).parents[1]/'scripts/download_file_fast.py'
    spec=importlib.util.spec_from_file_location('download_test_transport',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        count=0
        mode='wrong-range'
        payload=b'a'*131072
        def do_GET(self):
            type(self).count+=1
            if self.mode=='forbidden':
                self.send_response(403);self.end_headers();return
            body=self.payload
            if self.mode=='wrong-range':
                self.send_response(206)
                self.send_header('Content-Range',f'bytes 1-{len(body)}/{len(body)+1}')
            else:self.send_response(200)
            if self.mode=='html':body=b'<html>please login</html>'
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            try:self.wfile.write(body)
            except (ConnectionError,OSError):pass
        def log_message(self,*a):pass
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    try:yield Handler,f'http://127.0.0.1:{service.server_port}/weight.bin'
    finally:service.shutdown();service.server_close();thread.join(3)


def test_malformed_probe_range_is_rejected(client,server):
    handler,url=server
    with pytest.raises(RuntimeError,match='Content-Range'):client.fetch_size(url)
    result=bounded_probe(client,url,'weight.bin')
    assert result['status']=='FAIL' and result['category']=='invalid_response'


def test_wrong_resume_range_is_never_appended_or_published(client,server,tmp_path):
    handler,url=server
    output=tmp_path/'weight.bin';partial=client._stream_part_path(output,'identity')
    partial.write_bytes(b'good-prefix')
    assert client.stream_download(url,output,len(handler.payload),'a'*64,host='identity')==1
    assert partial.read_bytes()==b'good-prefix'
    assert not output.exists()
    assert handler.count==1


def test_range_ignored_light_check_has_hard_body_limit(client,server):
    handler,url=server;handler.mode='ignore'
    result=bounded_probe(client,url,'weight.bin',limit=4096)
    assert result['status']=='PASS' and result['consumed_bytes']==4096
    assert result['scope'].startswith('reachability only')


def test_html_with_binary_mime_is_rejected(client,server,tmp_path):
    handler,url=server;handler.mode='html'
    assert client.stream_download(url,tmp_path/'weight.bin',len(b'<html>please login</html>'),None)==1
    assert not (tmp_path/'weight.bin').exists()
    assert handler.count==1


def test_authorization_is_not_retried(client,server,tmp_path):
    handler,url=server;handler.mode='forbidden'
    assert client.stream_download(url,tmp_path/'weight.bin',100,None)==1
    assert handler.count==1


def test_cli_failed_transfer_emits_category_without_traceback(client,server,tmp_path):
    handler,url=server;handler.mode='ignore'
    # Metadata succeeds; the complete body cannot match the locked hash.
    result=subprocess.run([sys.executable,str(Path(client.__file__)), '--url',url,
        '--out',str(tmp_path/'weight.bin'),'--sha256','a'*64,'--source-mode','MODELSCOPE'],capture_output=True,text=True,encoding='utf8',timeout=30)
    assert result.returncode==1
    assert 'UnboundLocalError' not in result.stdout+result.stderr
    events=[json.loads(l.split(' ',1)[1]) for l in result.stdout.splitlines() if l.startswith('[2BYTEASR_ERROR] ')]
    assert events and events[-1]['category']=='checksum'


def test_signed_urls_and_relative_error_urls_are_sanitized():
    text='https://u:p@cdn.example/w?X-Amz-Signature=secret&token=abc with url: /w?sig=secret (failed)'
    clean=redact(text)
    assert 'secret' not in clean and 'u:p' not in clean and 'abc' not in clean


def test_source_cannot_weaken_hash_or_missing_files_contract():
    spec=dict(repository='official/model',revision='fixed',modelscope_repository='official/model',
              required_files=['weight.bin','config.json'],sha256={'weight.bin':'a'*64},
              source_manifests={'modelscope':{'files':['config.json'],'sha256':{}}})
    source=repo.source_manifest(spec,'MODELSCOPE')
    assert source.sha256['weight.bin']=='a'*64
    assert set(source.files)=={'config.json','weight.bin'}


def test_shard_index_cannot_install_undeclared_weight(tmp_path):
    (tmp_path/'model.index.json').write_text(json.dumps({'weight_map':{'a':'missing.bin'}}))
    manifest=repo.SourceManifest('HF_OFFICIAL','official/model','rev',('model.index.json',),{})
    assert not repo.validate_files(tmp_path,manifest)[0]


def test_crashed_publication_remains_partial_and_retry_finishes(tmp_path,monkeypatch):
    from twobyteasr.model_registry import _health_for,ModelHealth
    payload=b'valid';target=tmp_path/'model';target.mkdir()
    (target/'weight.bin').write_bytes(payload)
    (target/'.2byteasr-install-pending.json').write_text('{}')
    digest=hashlib.sha256(payload).hexdigest()
    spec=dict(repository='official/model',revision='rev',required_files=['weight.bin'],sha256={'weight.bin':digest})
    assert _health_for(target,('weight.bin',),{},True)[0]==ModelHealth.PARTIAL
    monkeypatch.setattr(repo,'download_source',lambda *a,**kw:pytest.fail('healthy weight must not be downloaded'))
    repo.download_model(model_key='fixture',spec=spec,destination=target,mode='HF_OFFICIAL',staging_root=tmp_path/'stage')
    assert _health_for(target,('weight.bin',),{'weight.bin':digest},True)[0]==ModelHealth.INSTALLED
    assert json.loads((target/'.2byteasr-source.json').read_text())['files'][0]['reused_installed']


def test_auto_tries_third_party_mirror_only_after_official_host():
    # 2026-10-14: huggingface.co is unreachable from mainland China without a
    # proxy, so AUTO ends with the third-party mirror; it is never tried first
    # and its files still have to match the locked hashes.
    sources=repo.planned_sources(dict(repository='official/model',revision='rev'), 'AUTO')
    assert [s.mode for s in sources]==['HF_OFFICIAL','HF_MIRROR']


@pytest.fixture
def routed_server():
    class Handler(BaseHTTPRequestHandler):
        requests=[]
        weight=b'controlled real weight\x00'*8192
        def do_GET(self):
            type(self).requests.append((self.path,self.headers.get('Range','')))
            if self.path.startswith('/primary/') and self.path.endswith('weight.bin'):
                self.send_response(302);self.send_header('Location','/expired?Signature=secret');self.end_headers();return
            if self.path.startswith('/expired'):
                self.send_response(403);self.end_headers();return
            if self.path.startswith('/429'):
                self.send_response(429);self.end_headers();return
            if self.path.startswith('/416'):
                self.send_response(416);self.end_headers();return
            if self.path.startswith('/slow'):
                time.sleep(.2)
            body=b'{}' if self.path.endswith('config.json') else self.weight
            size=len(body)
            if self.headers.get('Range'):
                lo,hi=self.headers['Range'].removeprefix('bytes=').split('-')
                lo=int(lo);hi=min(int(hi) if hi else size-1,size-1)
                body=body[lo:hi+1]
                self.send_response(206);self.send_header('Content-Range',f'bytes {lo}-{hi}/{size}')
            else:self.send_response(200)
            self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except OSError:pass
        def log_message(self,*a):pass
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    try:yield Handler,f'http://127.0.0.1:{service.server_port}'
    finally:service.shutdown();service.server_close();thread.join(3)


def test_real_subprocess_fallback_after_config_success_and_redirect_failure(routed_server,tmp_path,monkeypatch):
    handler,host=routed_server
    monkeypatch.setenv('TWOBYTEASR_DOWNLOAD_PYTHON',sys.executable)
    monkeypatch.setattr(repo,'_artifact_url',lambda manifest,name:host+('/primary/' if manifest.mode=='MODELSCOPE' else '/backup/')+name)
    spec=dict(repository='official/model',revision='fixed',modelscope_repository='official/model',
        required_files=['config.json','weight.bin'],sha256={'config.json':hashlib.sha256(b'{}').hexdigest(),'weight.bin':hashlib.sha256(handler.weight).hexdigest()})
    target=tmp_path/'中文 空格/models'
    assert repo.download_model(model_key='model',spec=spec,destination=target,mode='AUTO',staging_root=tmp_path/'中文 空格/stage')=='HF_OFFICIAL'
    assert (target/'weight.bin').read_bytes()==handler.weight
    paths=[p for p,r in handler.requests]
    assert '/primary/config.json' in paths and any(p.startswith('/expired') for p in paths) and '/backup/weight.bin' in paths
    receipt=json.loads((target/'.2byteasr-source.json').read_text())
    assert 'secret' not in json.dumps(receipt)


def test_rate_limit_has_bounded_metadata_retries(client,routed_server):
    handler,host=routed_server
    with pytest.raises(Exception):client.fetch_size(host+'/429')
    assert len(handler.requests)==client.RETRIES


def test_416_is_not_complete_and_keeps_partial(client,routed_server,tmp_path):
    handler,host=routed_server
    target=tmp_path/'weight.bin';part=client._stream_part_path(target,'known')
    part.write_bytes(b'old')
    assert client.stream_download(host+'/416',target,100,'a'*64,host='known')==1
    assert not target.exists() and part.read_bytes()==b'old'
    assert len(handler.requests)==1


def test_header_timeout_is_bounded_and_classified(client,routed_server):
    from twobyteasr.download_diagnostics import category
    handler,host=routed_server
    with pytest.raises(Exception) as error:client.fetch_size(host+'/slow',timeout=(.05,.05))
    assert category(error.value)=='network_timeout'
    assert len(handler.requests)==client.RETRIES


def test_changed_same_size_identity_cannot_reuse_old_complete_file(client,routed_server,tmp_path):
    handler,host=routed_server
    target=tmp_path/'weight.bin';target.write_bytes(b'x'*len(handler.weight))
    assert client.download_from_source(host+'/backup/weight.bin',target,len(handler.weight),True,4,
        hashlib.sha256(handler.weight).hexdigest(),0,10)==0
    assert target.read_bytes()==handler.weight and handler.requests


def test_corrupt_chunks_fail_publication_and_can_be_repaired(client,tmp_path):
    parts=[tmp_path/'a.part',tmp_path/'b.part']
    for part in parts:part.write_bytes(b'bad')
    target=tmp_path/'model.bin'
    with pytest.raises(RuntimeError,match='SHA-256'):client._publish_parts(target,parts,6,hashlib.sha256(b'foobar').hexdigest())
    assert not target.exists() and not any(p.exists() for p in parts)
    for part,body in zip(parts,[b'foo',b'bar']):part.write_bytes(body)
    client._publish_parts(target,parts,6,hashlib.sha256(b'foobar').hexdigest())
    assert target.read_bytes()==b'foobar'


def test_worker_crash_is_failure_and_does_not_publish(tmp_path,monkeypatch):
    manifest=repo.SourceManifest('HF_OFFICIAL','official/model','rev',('weight.bin',),{})
    monkeypatch.setenv('TWOBYTEASR_DOWNLOAD_PYTHON',sys.executable)
    def crash(*a,**kw):
        return subprocess.Popen([sys.executable,'-c','import os;os._exit(7)'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    monkeypatch.setattr(repo,'run_hidden_subprocess',crash)
    with pytest.raises(repo.SourceAttemptError,match='退出码 7'):repo._download_direct(manifest,tmp_path,'weight.bin')
    assert not (tmp_path/'weight.bin').exists()


def test_missing_worker_interpreter_reports_runtime_not_source(tmp_path,monkeypatch):
    monkeypatch.delenv('TWOBYTEASR_DOWNLOAD_PYTHON',raising=False)
    monkeypatch.setattr(repo,'main_python_executable',lambda *a:None)
    manifest=repo.SourceManifest('HF_OFFICIAL','official/model','rev',('weight.bin',),{})
    with pytest.raises(repo.SourceAttemptError,match='主运行环境尚未配置'):repo._download_direct(manifest,tmp_path,'weight.bin')
