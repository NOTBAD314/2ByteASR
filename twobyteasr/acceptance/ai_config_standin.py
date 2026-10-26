"""Loopback-only deterministic HTTP peer for live configuration acceptance."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class AiConfigStandin:
    def __init__(self):
        self.requests = []
        self.releases = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, payload):
                data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == '/requests':
                    self.reply(owner.requests)
                else:
                    self.reply({'data': [{'id': name} for name in ('model-A', 'model-B', 'model-C')]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                if self.path == '/control':
                    event = owner.releases.setdefault(body['model'], threading.Event())
                    event.clear() if body['pause'] else event.set()
                    self.reply({'ok': True})
                    return
                model = body['model']
                auth = self.headers.get('Authorization', '')
                credential = next((label for label in ('A', 'B', 'C')
                                   if auth == 'Bearer sk-ai-live-' + label), 'none-or-unknown')
                try:
                    request = json.loads(body['messages'][-1]['content'])
                except (ValueError, KeyError):
                    request = {}
                grouped = 'total_length' in request
                owner.requests.append({'model': model, 'credential_label': credential,
                                       'kind': 'grouped' if grouped else 'connection_test'})
                if model == 'model-failed-check':
                    data=json.dumps({'error':{'message':'fixture: selected model is unavailable'}}).encode()
                    self.send_response(400);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                    return
                if model in owner.releases:
                    owner.releases[model].wait(30)
                answer = {'boundaries': [request['total_length']]} if grouped else {'ok': True, 'text': '兔白字幕'}
                self.reply({'choices': [{'message': {'role': 'assistant', 'content': json.dumps(answer, ensure_ascii=False)},
                                         'finish_reason': 'stop'}], 'usage': {'total_tokens': 24}})

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def close(self):
        for event in self.releases.values():
            event.set()
        self.http.shutdown()
        self.thread.join(3)
        self.http.server_close()
