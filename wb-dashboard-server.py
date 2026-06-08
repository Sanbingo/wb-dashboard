#!/usr/bin/env python3
"""
WB 日报网页服务器
1. 提供静态HTML页面
2. /api/wb-daily?date=YYYY-MM-DD 接口返回数据

用法: python3 wb-dashboard-server.py [端口号]
默认端口: 8080
"""
import json
import subprocess
import os
import sys
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
            # Cache to file
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
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        
        if path == '/api/wb-daily':
            self.handle_api(params)
        elif path == '/api/mappings':
            self.handle_get_mappings()
        elif path == '/':
            self.serve_file('wb-dashboard.html', 'text/html; charset=utf-8')
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
        # Also support single date param for backward compat
        date_str = params.get('date', [None])[0]
        
        now_utc = datetime.now(timezone.utc)
        if date_str:
            start = end = date_str
        elif not start:
            start = end = (now_utc - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
        elif not end:
            end = start
        
        force = params.get('force', [None])[0]
        is_today = is_force_refresh = (force == 'true')
        
        # Check cache first (skip if force refresh)
        cache_file = get_data_file(start, end)
        cached_data = None
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
            except:
                pass
        
        if is_force_refresh:
            # 优先拉取实时数据
            data = fetch_data(start, end)
            # 拉取失败则回退到缓存
            if (not data or data.get('error')) and cached_data:
                data = cached_data
        else:
            data = cached_data if cached_data else fetch_data(start, end)
        
        self.send_json(data)
    
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/mappings':
            self.handle_save_mappings()
        else:
            self.send_error(404)
    
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
    
    def serve_file(self, filename, content_type, binary=False):
        filepath = os.path.join(WORKSPACE, filename)
        if not os.path.exists(filepath):
            # Check data dir
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            if binary:
                self.wfile.write(content)
            else:
                self.wfile.write(content.encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))
    
    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))
    
    def log_message(self, format, *args):
        ts = datetime.now().strftime('%H:%M:%S')
        print(f'[{ts}] {args[0]} {args[1]} {args[2]}')


def main():
    print(f"""
🦊 WB 销售日报 服务器
━━━━━━━━━━━━━━━━━━━━
📍 地址: http://localhost:{PORT}
📊 接口: http://localhost:{PORT}/api/wb-daily?date=YYYY-MM-DD
📁 工作目录: {WORKSPACE}
━━━━━━━━━━━━━━━━━━━━
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
