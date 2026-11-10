"""A deterministic Ollama-compatible model for the cross-peer run.

POST /api/chat answers the analysis-output JSON ClientSt0r's Rem0te prompt
asks for, citing the ticket body (and the first endpoint segment when there
is one) by the refs it finds in the prompt. The same prompt always gets the
same answer. GET /calls returns how many chat calls it has served (so the
runner can prove "at most one model call per run"); POST /delay {"seconds": n}
makes later calls slow (to revoke access while a job is mid-run).

    python llm_stub.py <port>
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS = []
DELAY = {'seconds': 0.0}
REF = re.compile(r'\[((?:ticket|endpoint):[^\]\s]+)\]')


def answer(user_text):
    refs = REF.findall(user_text)
    body = next((r for r in refs if r.endswith('#body')), refs[0] if refs else '')
    device = next((r for r in refs if r.startswith('endpoint:')), None)
    facts = [{'statement': 'The customer reports the front desk printer has not printed since this morning.',
              'evidence_refs': [body] if body else []}]
    if device:
        facts.append({'statement': 'Rem0te reports the front desk computer online.', 'evidence_refs': [device]})
    out = {
        'category': 'printing',
        'summary': 'Printing stopped on the front desk PC; the print spooler may have stopped.',
        'facts': facts,
        'hypotheses': [{'statement': 'The Print Spooler service has stopped on the front desk PC.',
                        'confidence': 'medium', 'evidence_refs': [body] if body else []}],
        'draft_reply': 'Thanks for letting us know. We are checking the print service on the front desk PC now '
                       'and will update you within the hour.',
        'next_steps': ['Check whether the Print Spooler service is running.'],
    }
    return json.dumps(out)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/calls':
            return self._send(200, {'calls': len(CALLS), 'models': [c['model'] for c in CALLS]})
        if self.path == '/api/tags':
            return self._send(200, {'models': [{'name': 'stub-triage'}]})
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        data = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/delay':
            DELAY['seconds'] = float(data.get('seconds') or 0)
            return self._send(200, DELAY)
        if self.path != '/api/chat':
            return self._send(404, {})
        user = next((m['content'] for m in data.get('messages', []) if m.get('role') == 'user'), '')
        CALLS.append({'model': data.get('model')})
        if DELAY['seconds']:
            time.sleep(DELAY['seconds'])
        self._send(200, {'model': data.get('model'), 'message': {'role': 'assistant', 'content': answer(user)},
                         'done': True, 'prompt_eval_count': len(user) // 4, 'eval_count': 120})


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
