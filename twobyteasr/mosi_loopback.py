"""Loopback stand-in for the MOSI transcription API, for acceptance runs only (2026-10-13).

Serves ``/v1/models``, ``POST /v1/audio/transcriptions`` and
``/v1/audio/tasks/{id}`` on 127.0.0.1 with the documented shapes, returning
sentences from a synthetic reference script (their real utterance times and
speakers). It exercises the app's upload/poll/parse/save path without a key or
network; it does no recognition and proves nothing about accuracy.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPEAKERS = {'M1': 'S01', 'F1': 'S02', 'F2': 'S03'}


def start(reference: dict):
    state = {'uploads': [], 'polls': 0}
    segments = [{'speaker': SPEAKERS.get(u['speaker'], 'S01'), 'text': u['text'], 'start': u['start_s'],
                 'end': u['end_s']} for u in reference['utterances']]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/v1/models':
                return self._send(200, {'object': 'list', 'data': [{'id': 'moss-transcribe-diarize-pro'}]})
            if self.path.startswith('/v1/audio/tasks/'):
                state['polls'] += 1
                return self._send(200, {'id': 'loop', 'status': 'SUCCESS',
                                        'text': ''.join(s['text'] for s in segments), 'segments': segments})
            self._send(404, {'error': {'code': 'not_found'}})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length)
            state['uploads'].append({'bytes': len(body), 'authorized': self.headers.get('Authorization', '').startswith('Bearer ')})
            self._send(200, {'id': 'loop', 'task_id': 'loop', 'status': 'PENDING', 'retry_after': 2})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='mosi-loopback').start()
    return server, state
