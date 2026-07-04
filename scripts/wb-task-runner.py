#!/usr/bin/env python3
"""
WB 定时任务执行器
每小时由 crontab 调用，检查所有启用的定时任务，
执行仓库查询并发送飞书通知。
"""
import json
import os
import sys
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta

WORKSPACE = '/opt/wb-dashboard'
DATA_DIR = os.path.join(WORKSPACE, 'data')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.json')
CONFIG_FILE = os.path.join(WORKSPACE, 'config.py')

def load_tasks():
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'tasks': []}

def save_tasks(tasks_data):
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks_data, f, ensure_ascii=False, indent=2)

def send_feishu(webhook_url, title, content):
    if not webhook_url:
        return False
    msg = {
        'msg_type': 'interactive',
        'card': {
            'header': {'title': {'tag': 'plain_text', 'content': title}, 'template': 'blue'},
            'elements': [{'tag': 'markdown', 'content': content}]
        }
    }
    payload = json.dumps(msg).encode('utf-8')
    req = urllib.request.Request(webhook_url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json; charset=utf-8')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        return result.get('code') == 0
    except:
        return False

def fetch_offices():
    """从WB API获取仓库列表"""
    cfg_globals = {}
    with open(CONFIG_FILE) as f:
        exec(f.read(), cfg_globals)
    token_file = cfg_globals.get('WB_TOKEN_FILE', '/opt/wb-scripts/secrets/wb-api.json')
    with open(token_file) as f:
        cfg = json.load(f)
    token = cfg['jwt'].strip()
    
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request('https://marketplace-api.wildberries.ru/api/v3/offices', method='GET')
    req.add_header('Authorization', token)
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    return json.loads(resp.read().decode('utf-8'))

def load_webhook():
    """从warehouses.json读取飞书webhook"""
    wf = os.path.join(DATA_DIR, 'warehouses.json')
    if os.path.exists(wf):
        try:
            with open(wf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('settings', {}).get('feishuWebhook', '')
        except:
            pass
    return ''

def run():
    tasks_data = load_tasks()
    tasks = tasks_data.get('tasks', [])
    now = datetime.now(timezone.utc)
    
    enabled_tasks = [t for t in tasks if t.get('enabled', False)]
    if not enabled_tasks:
        print(f'[{now}] No enabled tasks')
        return
    
    print(f'[{now}] Running {len(enabled_tasks)} task(s)...')
    
    # 获取WB仓库数据
    try:
        offices_data = fetch_offices()
        offices = offices_data if isinstance(offices_data, list) else offices_data.get('offices', [])
    except Exception as e:
        print(f'  Failed to fetch offices: {e}')
        return
    
    webhook = load_webhook()
    
    for task in enabled_tasks:
        task_name = task.get('warehouses', ['?'])[0] if task.get('warehouses') else '?'
        task_id = task.get('id', '?')
        target_date = task.get('date', '')
        delivery_type = task.get('deliveryType', '箱子')
        
        print(f'  Task {task_id}: {task_name} ({target_date})')
        
        # 匹配仓库
        warehouse_names = task.get('warehouseNames', []) or task.get('warehouses', [])
        results = []
        for wn in warehouse_names:
            matches = [o for o in offices if wn.lower() in o.get('name', '').lower() or o.get('name', '').lower() in wn.lower()]
            results.append({'name': wn, 'found': len(matches) > 0, 'count': len(matches)})
        
        available = [r for r in results if r['found']]
        
        # 有可用的就发通知
        if available and webhook:
            avail_names = [r['name'] for r in available]
            title = f'✅ {target_date} 可预约仓库'
            content = f'🕐 查询日期：{target_date}\n'
            content += f'🏭 可用仓库：{", ".join(avail_names)}\n'
            content += f'📦 配送方式：{delivery_type}\n'
            content += f'📊 {len(available)}/{len(results)} 个仓库可预约'
            send_feishu(webhook, title, content)
            print(f'    Sent Feishu: {len(available)} available')
        elif not available:
            print(f'    No available warehouses')
    
    # 更新 lastRunAt
    now_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    for t in tasks:
        if t.get('enabled', False):
            t['lastRunAt'] = now_str
    save_tasks({'tasks': tasks})

if __name__ == '__main__':
    run()
