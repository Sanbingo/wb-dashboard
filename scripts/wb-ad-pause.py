#!/usr/bin/env python3
"""
WB 广告暂停脚本
每天07:15 由系统cron执行
暂停广告ID 35674574（早间暂停）
"""
import json
import subprocess
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LOG_DIR, WB_PROXY
from lib.feishu import get_tenant_token, send_text_to_group

LOG_FILE = f"{LOG_DIR}/wb-ad-pause.log"


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}')


def pause_ad(ad_id):
    """暂停广告"""
    with open(os.path.expanduser('~/.openclaw/workspace/secrets/wb-api.json')) as f:
        token = json.load(f)['jwt']
    
    r = subprocess.run(
        ['curl', '-s', '-H', f'Authorization: {token}',
         f'https://advert-api.wildberries.ru/adv/v0/pause?id={ad_id}'],
        capture_output=True, text=True, timeout=15
    )
    
    # 空响应=成功
    if not r.stdout.strip():
        log(f"广告 {ad_id} 暂停成功")
        return True
    else:
        log(f"广告 {ad_id} 暂停返回: {r.stdout[:100]}")
        return False


def main():
    log("=== WB广告暂停开始 ===")
    
    try:
        ad_id = 35674574
        result = pause_ad(ad_id)
        
        token = get_tenant_token()
        if result:
            send_text_to_group(token, f"⏸️ WB广告已暂停\n广告 {ad_id} ✅\n北京时间7:15自动暂停")
        else:
            send_text_to_group(token, f"⚠️ WB广告暂停可能失败，请检查\n广告ID: {ad_id}")
        
        log(f"=== WB广告暂停完成 ===")
        
    except Exception as e:
        log(f"❌ 失败: {e}")
        try:
            tk = get_tenant_token()
            send_text_to_group(tk, f"❌ WB广告暂停异常: {str(e)[:200]}")
        except:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
