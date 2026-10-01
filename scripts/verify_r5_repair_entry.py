"""Prepare a fresh isolated normal-entry audit; --live consumes exactly 1+1 requests."""
import argparse
import datetime
import json
import os
from pathlib import Path
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use a new tmp directory')
    from twobyteasr.processes import run_hidden_subprocess
    original_local=Path(os.environ['LOCALAPPDATA'])
    run_hidden_subprocess([sys.executable,str(root/'scripts/verify_normal_ai_entry.py'),'--output',str(out),
        '--service','deepseek','--model','deepseek-v4-pro','--text-only','--prepare-only'],
        check=True,timeout=90,capture_output=True,purpose='prepare isolated r5 acceptance fixture')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME,'localhost')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
        .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False).sign(key,hashes.SHA256()))
    (out/'local-cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (out/'local-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'local TLS control')
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(out/'local-cert.pem',out/'local-key.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    config=json.loads((out/'run-config.json').read_text('utf8'))
    config['local_tls']=dict(port=server.server_port,ca=str(out/'local-cert.pem'))
    (out/'run-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        TEMP=str(out/'temp'),TMP=str(out/'temp'),PYTHONUTF8='1',PYTHONIOENCODING='utf8',QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='r5-repair-live',
        TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE=str(original_local/'2ByteASR/secrets.dat'),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_R5_LIVE='1' if args.live else '0',
        NO_PROXY=env.get('NO_PROXY','')+',localhost,127.0.0.1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    try:
        code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=650)
    finally:server.shutdown()
    result=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps(dict(exit_code=code,completed=result.get('completed'),ui_verified=result.get('ui_verified'),
        calls=[dict(kind=c['kind'],status=c['status']) for c in result['calls']],error=result.get('error'))))
    return code


if __name__=='__main__':raise SystemExit(main())
