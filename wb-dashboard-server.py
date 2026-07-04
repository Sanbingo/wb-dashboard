#!/usr/bin/env python3
"""
WB 日报网页服务器
1. 提供静态HTML页面
2. API接口
3. 用户登录/会话管理

用法: python3 wb-dashboard-server.py [端口号]
默认端口: 8080
"""
import json
import subprocess
import os
import sys
import uuid
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timezone, timedelta

HOST = '0.0.0.0'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(WORKSPACE, 'scripts') if os.path.isdir(os.path.join(WORKSPACE, 'scripts')) else WORKSPACE
DATA_DIR = os.path.join(WORKSPACE, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# 会话配置
SESSION_FILE = os.path.join(DATA_DIR, 'sessions.json')
SESSION_TTL = 86400  # 24小时
LOGIN_USER = 'WB'
LOGIN_PASS = '000111'

WAREHOUSE_FILE = os.path.join(DATA_DIR, 'warehouses.json')

PROTECTED_PATHS = ['/wb-dashboard.html', '/wb-settings.html', '/wb-inventory.html', '/wb-booking.html', '/api/wb-daily', '/api/mappings', '/api/wb-offices', '/api/send-feishu', '/api/warehouses']


def load_sessions():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f)


def create_session():
    token = uuid.uuid4().hex
    expires = time.time() + SESSION_TTL
    sessions = load_sessions()
    sessions[token] = expires
    save_sessions(sessions)
    return token, expires


def check_session(token):
    if not token:
        return False
    sessions = load_sessions()
    now = time.time()
    # Clean expired sessions
    expired = [k for k, v in sessions.items() if v < now]
    for k in expired:
        del sessions[k]
    if expired:
        save_sessions(sessions)
    
    expires = sessions.get(token)
    if expires and expires > now:
        return True
    return False


def get_data_file(start_date, end_date=None):
    if end_date and end_date != start_date:
        key = f'{start_date}_{end_date}'
    else:
        key = start_date
    return os.path.join(DATA_DIR, f'wb-daily-{key}.json')


def fetch_data(start_date, end_date=None):
    """调用数据脚本获取数据"""
    script = os.path.join(SCRIPT_DIR, 'wb-dashboard-data.py')
    if not os.path.exists(script):
        return {'error': f'脚本不存在: {script}'}
    
    try:
        cmd = ['python3', script, '--date', start_date] if start_date == end_date or not end_date else \
              ['python3', script, '--start', start_date, '--end', end_date]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        stdout = r.stdout.decode('utf-8', errors='replace') if isinstance(r.stdout, bytes) else r.stdout
        stderr = r.stderr.decode('utf-8', errors='replace') if isinstance(r.stderr, bytes) else r.stderr
        if r.returncode != 0:
            return {'error': f'脚本执行失败: {stderr[:500]}'}
        
        data = json.loads(stdout)
        if isinstance(data, dict) and 'summary' in data:
            with open(get_data_file(start_date, end_date), 'w', encoding='utf-8') as f:
                f.write(stdout)
            return data
        else:
            return {'error': '数据格式异常'}
    except json.JSONDecodeError as e:
        return {'error': f'JSON解析失败: {str(e)}'}
    except subprocess.TimeoutExpired:
        return {'error': '脚本执行超时'}
    except Exception as e:
        return {'error': str(e)}


class DashboardHandler(BaseHTTPRequestHandler):
    
    def is_protected(self, path):
        clean = path.rstrip('/')
        for p in PROTECTED_PATHS:
            if clean.startswith(p):
                return True
        return False
    
    def get_session_token(self):
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            part = part.strip()
            if part.startswith('wb_session='):
                return part[11:]
        return None
    
    def require_auth(self):
        """Check auth, redirect to login if needed (for GET HTML requests)"""
        token = self.get_session_token()
        return check_session(token)
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        
        # Login page - no auth required
        if path == '/login.html':
            self.serve_file('wb-login.html', 'text/html; charset=utf-8')
            return
        
        # Check session API
        if path == '/api/check-session':
            token = self.get_session_token()
            valid = check_session(token)
            self.send_json({'valid': valid})
            return
        
        # Protected paths
        if self.is_protected(path):
            if not self.require_auth():
                self.send_redirect('/login.html')
                return
        
        if path == '/api/wb-daily':
            self.handle_api(params)
        elif path == '/api/mappings':
            self.handle_get_mappings()
        elif path == '/api/wb-offices':
            self.handle_wb_offices()
        elif path == '/api/warehouses':
            self.handle_get_warehouses()
        elif path == '/':
            # Root - redirect to dashboard
            self.send_redirect('/wb-dashboard.html')
        elif path.endswith('.html'):
            self.serve_file(path.lstrip('/'), 'text/html; charset=utf-8')
        elif path.endswith('.js'):
            self.serve_file(path.lstrip('/'), 'application/javascript; charset=utf-8')
        elif path.endswith('.css'):
            self.serve_file(path.lstrip('/'), 'text/css; charset=utf-8')
        elif path.endswith('.json'):
            self.serve_file(path.lstrip('/'), 'application/json; charset=utf-8')
        elif path.startswith('/data/'):
            filepath = path.lstrip('/')
            self.serve_file(filepath, 'application/json; charset=utf-8', binary=False)
        else:
            self.send_error(404, 'Not Found')
    
    def handle_api(self, params):
        start = params.get('start', [None])[0]
        end = params.get('end', [None])[0]
        date_str = params.get('date', [None])[0]
        
        now_utc = datetime.now(timezone.utc)
        if date_str:
            start = end = date_str
        elif not start:
            start = end = (now_utc - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
        elif not end:
            end = start
        
        force = params.get('force', [None])[0]
        is_force_refresh = (force == 'true')
        
        cache_file = get_data_file(start, end)
        cached_data = None
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
            except:
                pass
        
        if is_force_refresh:
            data = fetch_data(start, end)
            if (not data or data.get('error')) and cached_data:
                data = cached_data
        else:
            data = cached_data if cached_data else fetch_data(start, end)
        
        self.send_json(data)
    
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if path == '/api/login':
            self.handle_login()
        elif path == '/api/mappings':
            # Check auth for mappings save
            if not self.require_auth():
                self.send_json({'error': 'unauthorized'}, 401)
                return
            self.handle_save_mappings()
        elif path == '/api/send-feishu':
            self.handle_send_feishu()
        elif path == '/api/warehouses':
            if not self.require_auth():
                self.send_json({'error': 'unauthorized'}, 401)
                return
            self.handle_save_warehouses()
        else:
            self.send_error(404)
    
    def handle_login(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            username = data.get('username', '')
            password = data.get('password', '')
            
            if username == LOGIN_USER and password == LOGIN_PASS:
                token, expires = create_session()
                max_age = SESSION_TTL
                expires_str = datetime.fromtimestamp(expires, tz=timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
                cookie = f'wb_session={token}; Path=/; Max-Age={max_age}; Expires={expires_str}; SameSite=Lax'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Set-Cookie', cookie)
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
            else:
                self.send_json({'success': False, 'error': '账号或密码错误'})
        except Exception as e:
            self.send_json({'success': False, 'error': str(e)})
    
    def handle_get_mappings(self):
        path = os.path.join(DATA_DIR, 'mappings.json')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json(data)
                return
            except:
                pass
        self.send_json({})
    
    def handle_save_mappings(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            path = os.path.join(DATA_DIR, 'mappings.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.send_json({'status': 'ok'})
        except Exception as e:
            self.send_json({'error': str(e)})
    
    def handle_wb_offices(self):
        """获取WB仓库/办公室列表"""
        import urllib.request
        import ssl as _ssl
        try:
            # 从config.py获取token
            config_path = os.path.join(WORKSPACE, 'config.py')
            cfg_globals = {}
            with open(config_path) as f:
                exec(f.read(), cfg_globals)
            token_file = cfg_globals.get('WB_TOKEN_FILE', '/opt/wb-scripts/secrets/wb-api.json')
            with open(token_file) as f:
                cfg = json.load(f)
            token = cfg['jwt'].strip()
            
            ctx = _ssl._create_unverified_context()
            
            # 获取全部办公室/仓库（WB API一次返回全部）
            req = urllib.request.Request(
                'https://marketplace-api.wildberries.ru/api/v3/offices',
                method='GET')
            req.add_header('Authorization', token)
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            offices = json.loads(resp.read().decode('utf-8'))
            
            self.send_json({'offices': offices, 'total': len(offices)})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if hasattr(e, 'read') else str(e)
            self.send_json({'error': 'WB API error: ' + str(e.code) + ' ' + err_body[:200]}, 500)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def handle_send_feishu(self):
        """通过飞书Webhook发送消息"""
        import urllib.request
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            
            webhook = data.get('webhook', '').strip()
            title = data.get('title', 'WB 通知')
            content = data.get('content', '')
            
            if not webhook:
                self.send_json({'success': False, 'error': 'webhook为空'})
                return
            
            # 构建飞书消息 (支持 text 和 interactive 两种格式)
            msg_data = {
                'msg_type': 'interactive',
                'card': {
                    'header': {
                        'title': {'tag': 'plain_text', 'content': title},
                        'template': 'blue'
                    },
                    'elements': [
                        {
                            'tag': 'markdown',
                            'content': content
                        }
                    ]
                }
            }
            
            payload = json.dumps(msg_data).encode('utf-8')
            req = urllib.request.Request(webhook, data=payload, method='POST')
            req.add_header('Content-Type', 'application/json; charset=utf-8')
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read().decode('utf-8'))
            
            if result.get('code') == 0:
                self.send_json({'success': True})
            else:
                self.send_json({'success': False, 'error': result.get('msg', '发送失败')})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if hasattr(e, 'read') else str(e)
            self.send_json({'success': False, 'error': 'HTTP ' + str(e.code) + ': ' + err_body[:200]})
        except Exception as e:
            self.send_json({'success': False, 'error': str(e)})
    
    def handle_get_warehouses(self):
        """获取仓库列表"""
        if os.path.exists(WAREHOUSE_FILE):
            try:
                with open(WAREHOUSE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json(data)
                return
            except:
                pass
        self.send_json({'warehouses': [], 'settings': {}})
    
    def handle_save_warehouses(self):
        """保存仓库列表"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            with open(WAREHOUSE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.send_json({'status': 'ok'})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def send_redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.end_headers()
    
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))
    
    def serve_file(self, filename, content_type, binary=False):
        filepath = os.path.join(WORKSPACE, filename)
        if not os.path.exists(filepath):
            filepath = os.path.join(DATA_DIR, filename.split('/')[-1])
            if not os.path.exists(filepath):
                self.send_error(404, f'File not found: {filename}')
                return
        
        try:
            mode = 'rb' if binary else 'r'
            with open(filepath, mode, encoding=None if binary else 'utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            if binary:
                self.wfile.write(content)
            else:
                self.wfile.write(content.encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))
    
    def log_message(self, format, *args):
        ts = datetime.now().strftime('%H:%M:%S')
        if len(args) >= 3:
            print(f'[{ts}] {args[0]} {args[1]} {args[2]}')
        elif len(args) >= 1:
            print(f'[{ts}] {" ".join(str(a) for a in args)}')
        else:
            print(f'[{ts}] (empty log)')


def main():
    print(f"""
🦊 WB 销售日报 服务器
━━━━━━━━━━━━━━━━━━━━━
📍 地址: http://localhost:{PORT}
📊 接口: http://localhost:{PORT}/api/wb-daily
🔐 登录: POST /api/login (WB / 000111)
📁 工作目录: {WORKSPACE}
━━━━━━━━━━━━━━━━━━━━━
按 Ctrl+C 停止
""")
    
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        allow_reuse_address = True
        daemon_threads = True
    server = ThreadedHTTPServer((HOST, PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n👋 服务器已停止')
        server.server_close()


if __name__ == '__main__':
    main()
