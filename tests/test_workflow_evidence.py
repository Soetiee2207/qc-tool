"""Generic authenticated-prefix/destination evidence; no product constants."""
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from qctool.executability import analyze_executability
from qctool.testcase import Step, StepKind, TestCase
from qctool.test_fixtures import FixtureStore
from qctool.ui.crawl import Element, PageMap, UIMap
from tests.fixture_samples import note

BASE = 'https://workflow.example.test'


@pytest.fixture
def authenticated_app(request):
    counts = {'posts': 0, 'destination': 0}
    background = getattr(request, 'param', None)
    crowded_home = background == 'crowded_home'
    slow_login = background == 'slow_login'
    lazy_destination = background == 'lazy_destination'
    dense_destination = background in {'dense_destination', 'duplicate_destination', 'truncated_destination'}
    destination_kind = background
    if crowded_home or slow_login or lazy_destination or dense_destination:
        background = None
    foreign = None
    if background:
        counts['foreign_requests'] = 0
        class ForeignHandler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                counts['foreign_requests'] += 1
                self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers()
            do_POST = do_GET
        foreign = ThreadingHTTPServer(('127.0.0.1', 0), ForeignHandler)
        foreign_thread = threading.Thread(target=foreign.serve_forever, daemon=True)
        foreign_thread.start()
        counts['foreign_origin'] = f'http://127.0.0.1:{foreign.server_port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            counts['posts'] += 1
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if slow_login:
                import time
                time.sleep(0.6)
            self.send_response(200); self.send_header('Set-Cookie', 'auth=1; Path=/')
            self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"success":true,"token":"PRIVATE_RESPONSE"}')
        def do_GET(self):
            if self.path == '/view-data':
                import time
                time.sleep(0.7)
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(b'{}')
                return
            if self.path == '/destination' and 'auth=1' not in self.headers.get('Cookie', ''):
                self.send_response(302); self.send_header('Location', '/entry'); self.end_headers(); return
            if self.path == '/destination': counts['destination'] += 1
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            if self.path == '/entry':
                html = '''<label>Email<input type=email data-testid=email></label>
                <label>Password<input type=password data-testid=password></label><button data-testid=submit>Login</button>
                <script>document.querySelector('button').onclick=async()=>{await fetch('/api/session',{method:'POST',body:document.querySelector('[data-testid=password]').value});location.href='/home'};</script>'''
            elif self.path == '/destination':
                html = '<h1>Profile</h1><span>Customer</span><button data-testid=tab>All</button>'
                if dense_destination:
                    from qctool.ui.explore import MAX_ELEMENTS
                    count = MAX_ELEMENTS + 20 if destination_kind == 'truncated_destination' else 130
                    html += ''.join(f'<span>List row {i}</span>' for i in range(count))
                    if destination_kind == 'duplicate_destination':
                        html += '<h1>Profile</h1>'
                if lazy_destination:
                    html = '''<button>Persistent header</button><main></main><script>
                    fetch('/view-data').then(r=>r.json()).then(()=>{
                      document.querySelector('main').innerHTML='<h1>Profile</h1><span>Customer</span><button data-testid=tab>All</button>';
                    });</script>'''
            else: html = '<h1>Home</h1>'
            if self.path == '/home' and crowded_home:
                from qctool.ui.explore import MAX_ELEMENTS
                html += ''.join(f'<span>Unrelated content {i}</span>' for i in range(MAX_ELEMENTS + 20))
            if self.path == '/home' and background:
                method, path = background
                html += f"<script>fetch('http://127.0.0.1:{foreign.server_port}{path}?token=PRIVATE_QUERY',{{method:'{method}'}}).catch(()=>{{}})</script>"
            self.wfile.write(html.encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', counts
    server.shutdown(); server.server_close(); thread.join()
    if foreign:
        foreign.shutdown(); foreign.server_close(); foreign_thread.join()


@pytest.mark.parametrize('route', ['/delete-record', '/payment', '/upload', '/seed'])
def test_source_navigation_never_authorizes_destructive_operation(route):
    from qctool.agent.safety import SafetyPolicy, SafetyError
    with pytest.raises(SafetyError):
        SafetyPolicy('https://app.test').url(route)
