"""Fresh loopback-only acceptance app. No installed product/database is touched.

No deliberate bugs; four source-specified scenarios including in-memory fixture
creation. Counters retain method/path/status only; request bodies are never logged.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

SIGN_IN = '''<!doctype html><title>Sign in</title>
<form novalidate><label>Email<input type=email aria-label=Email data-testid=account-email></label>
<label>Password<input type=password aria-label=Password data-testid=account-password></label>
<button type=submit data-testid=session-submit>Login</button></form>
<p role=alert data-testid=form-feedback hidden></p><script>
document.querySelector('form').onsubmit=async(event)=>{
 event.preventDefault();const email=document.querySelector('input[type=email]').value;
 const password=document.querySelector('input[type=password]').value;
 const alert=document.querySelector('[role=alert]');
 if(!email||!password){alert.textContent='Both fields are required';alert.hidden=false;return;}
 const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
 const result=await response.json();if(response.status===200&&result.success){history.pushState({},'', '/workspace');document.body.innerHTML='<h1>Workspace</h1><button>Check</button>';document.title='Workspace';}
};</script>'''
PAGES = {
 '/entry': SIGN_IN,
 '/': '<title>Home</title><a href=/entry>Sign in</a><a href=/start>Start</a>',
 '/workspace': '<title>Workspace</title><h1>Workspace</h1><button>Check</button>',
 '/start': '<title>Start</title><a data-testid=preview-link href=/review>Preview</a>',
 '/review': '''<title>Review</title><label>Search<input aria-label=Search data-testid=search-field></label>
 <button data-testid=check-preview>Check</button><p role=alert data-testid=preview-feedback hidden></p>
 <script>document.querySelector('button').onclick=()=>{if(document.querySelector('input').value==='orchid'){
 const alert=document.querySelector('[role=alert]');alert.textContent='Search ready';alert.hidden=false;}};</script>''',
}


def create_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, status, content, content_type='application/json'):
            self.send_response(status); self.send_header('Content-Type', content_type+'; charset=utf-8')
            self.end_headers(); self.wfile.write(content.encode())
        def do_GET(self):
            if self.path in PAGES:
                self.reply(200, PAGES[self.path], 'text/html')
            else: self.reply(404, '{}')
        def do_POST(self):
            try: body=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length',0)),4096)))
            except (ValueError,TypeError): self.reply(400,'{}'); return
            with self.server.lock:
                if self.path=='/api/customers':
                    if set(body)!={'email','password','role'} or body['role']!='customer': status=400
                    elif body['email'] in self.server.users: status=409
                    else:
                        self.server.users[body['email']]={'password':body['password'],'role':'customer','account_state':'active'}
                        status=201
                elif self.path=='/api/session':
                    user=self.server.users.get(body.get('email'))
                    status=200 if user and user['account_state']=='active' and user['password']==body.get('password') else 401
                else: status=404
                self.server.calls.append({'method':'POST','path':self.path,'status':status})
            self.reply(status,json.dumps({'success':status in {200,201}}))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.users={};server.calls=[];server.lock=threading.Lock()
    return server
