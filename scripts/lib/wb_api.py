"""
Wildberries API 封装
"""
import json
import subprocess
import sys
sys.path.insert(0, '/Users/san/.openclaw/workspace/scripts')
from config import WB_TOKEN_FILE, WB_PROXY, LOG_DIR


def get_token():
    """读取WB JWT token"""
    with open(WB_TOKEN_FILE) as f:
        cfg = json.load(f)
    return cfg['jwt']


def api_get(path, use_proxy=True):
    """GET 请求 WB API"""
    token = get_token()
    cmd = ['curl', '-s']
    if use_proxy:
        cmd += ['-x', WB_PROXY]
    cmd += ['-H', f'Authorization: {token}']
    cmd += [path]
    
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    _log(f"GET {path} -> {r.stdout[:200]}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def api_post(path, data, use_proxy=True):
    """POST 请求 WB API"""
    token = get_token()
    cmd = ['curl', '-s']
    if use_proxy:
        cmd += ['-x', WB_PROXY]
    cmd += ['-X', 'POST',
            '-H', f'Authorization: {token}',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps(data)]
    cmd += [path]
    
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    _log(f"POST {path} -> {r.stdout[:200]}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _log(msg):
    with open(f'{LOG_DIR}/wb_api.log', 'a') as f:
        f.write(f'{msg}\n')
