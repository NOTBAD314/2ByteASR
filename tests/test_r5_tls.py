from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import ipaddress
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from twobyteasr.providers import network_policy as net


@pytest.fixture
def https_server(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'isolated local fixture')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        .sign(key,hashes.SHA256()))
    pem=tmp_path/'ca.pem';priv=tmp_path/'key.pem'
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(pem,priv)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'https://127.0.0.1:{server.server_port}',pem
    server.shutdown();server.server_close();thread.join()


def test_valid_isolated_ca_unknown_ca_and_missing_path(https_server,monkeypatch,tmp_path):
    url,pem=https_server
    for name in ('SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('NO_PROXY','127.0.0.1,localhost')
    with pytest.raises(net.NetworkTrustError) as error:
        net.get(url,timeout=2)
    assert error.value.category=='tls_certificate'
    monkeypatch.setenv('REQUESTS_CA_BUNDLE',str(pem))
    assert net.get(url,timeout=2).status_code==200
    with pytest.raises(net.NetworkTrustError):
        net.get(url.replace('127.0.0.1','localhost'),timeout=2,proxies={'https':None,'http':None})
    monkeypatch.setenv('REQUESTS_CA_BUNDLE',str(tmp_path/'missing.pem'))
    with pytest.raises(net.NetworkTrustError) as error:net.get(url,timeout=2)
    assert error.value.category=='tls_ca_path'


def test_frozen_ca_resolution_does_not_use_cwd(monkeypatch,tmp_path):
    import certifi
    import sys
    for name in ('SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE'):
        monkeypatch.delenv(name,raising=False)
    bundled=tmp_path/'bundle'/'certifi'/'cacert.pem'
    bundled.parent.mkdir(parents=True);bundled.write_bytes(__import__('pathlib').Path(certifi.where()).read_bytes())
    monkeypatch.setattr(certifi,'where',lambda:str(tmp_path/'old-dev-path.pem'))
    monkeypatch.setattr(sys,'_MEIPASS',str(bundled.parent.parent),raising=False)
    monkeypatch.chdir(tmp_path)
    assert net.ca_bundle()[0]==str(bundled)


def test_tls_never_suggests_manual_id_as_workaround(monkeypatch):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider,AIProviderError
    monkeypatch.setattr('twobyteasr.providers.ai_providers.fetch_openai_compatible_models',lambda *a,**k:(_ for _ in ()).throw(net.NetworkTrustError('证书失败')))
    provider=OpenAICompatibleProvider(dict(provider='deepseek',base_url='https://api.deepseek.com/v1',model='saved',api_key='dummy'))
    with pytest.raises(AIProviderError) as error:provider.discover_models(refresh=True)
    assert error.value.category=='tls_certificate' and '手动输入' not in str(error.value)
