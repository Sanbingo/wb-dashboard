#!/usr/bin/env python3
"""
WB 广告数据推送脚本
每天09:15 由系统cron执行
1. 调用WB广告API获取昨日广告数据
2. 汇总统计
3. 发送到飞书群聊
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LOG_DIR, WB_PROXY, WB_AD_IDS
from lib.feishu import get_tenant_token, send_text_to_group

LOG_FILE = f"{LOG_DIR}/wb-ad-push.log"


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}')


def get_wb_token():
    with open(os.path.expanduser('~/.openclaw/workspace/secrets/wb-api.json')) as f:
        return json.load(f)['jwt']


def get_ad_stats(msk_date):
    """获取广告昨日数据"""
    token = get_wb_token()
    ids = ','.join(str(i) for i in WB_AD_IDS)
    url = (f'https://advert-api.wildberries.ru/adv/v3/fullstats'
           f'?ids={ids}&period=day&beginDate={msk_date}&endDate={msk_date}')
    
    r = subprocess.run(
        ['curl', '-s', '-x', WB_PROXY,
         '-H', f'Authorization: {token}', url],
        capture_output=True, text=True, timeout=30
    )
    
    raw = json.loads(r.stdout) if r.stdout.strip() else {}
    # 处理API限流错误
    if isinstance(raw, dict) and (raw.get('status') == 429 or 'too many requests' in str(raw).lower()):
        log(f"⚠️ API限流，等待30秒后重试")
        time.sleep(30)
        r = subprocess.run(
            ['curl', '-s', '-x', WB_PROXY,
             '-H', f'Authorization: {token}', url],
            capture_output=True, text=True, timeout=30)
        raw = json.loads(r.stdout) if r.stdout.strip() else []
    
    # 确保返回列表
    if isinstance(raw, list):
        log(f"广告API返回: {len(raw)}条")
        return raw
    elif isinstance(raw, dict) and 'data' in raw:
        items = raw['data']
        log(f"广告API返回: {len(items) if isinstance(items, list) else 'dict'}条")
        return items if isinstance(items, list) else []
    else:
        log(f"广告API返回格式异常: {str(raw)[:200]}")
        return []

def parse_ad_stats(items):
    """解析广告统计数据"""
    if not isinstance(items, list):
        items = []
    
    ad_list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ad_id = item.get('advertId', item.get('advert_id', '?'))
        stats = item.get('statistics', item.get('stats', []))
        
        if isinstance(stats, list):
            cost = sum(s.get('sum', 0) for s in stats)
            clicks = sum(s.get('clicks', 0) for s in stats)
            atbs = sum(s.get('atbs', 0) for s in stats)
            orders = sum(s.get('orders', 0) for s in stats)
        else:
            cost = stats.get('sum', stats.get('cost', 0))
            clicks = stats.get('clicks', 0)
            atbs = stats.get('atbs', 0)
            orders = stats.get('orders', 0)
        
        ad_list.append({
            'advertId': ad_id,
            'cost': cost,
            'clicks': clicks,
            'atbs': atbs,
            'orders': orders
        })
    
    return ad_list


def format_report(ad_list, msk_date):
    """格式化为飞书消息"""
    total_cost = sum(a.get('cost', 0) for a in ad_list)
    total_clicks = sum(a.get('clicks', 0) for a in ad_list)
    total_atbs = sum(a.get('atbs', 0) for a in ad_list)
    total_orders = sum(a.get('orders', 0) for a in ad_list)
    
    lines = []
    for ad in ad_list:
        lines.append(
            f"广告 {ad.get('advertId', '?')}：花费 {ad['cost']:,.0f}₽ | "
            f"点击 {ad['clicks']} | 加购 {ad['atbs']} | 下单 {ad['orders']}"
        )
    
    text = (
        f"📊 WB广告数据（MSK {msk_date}）\n"
        f"━━━━━━━━━━━━━━━━\n"
    )
    text += '\n'.join(lines) if lines else "无数据"
    text += (
        f"\n━━━━━━━━━━━━━━━━\n"
        f"合计：花费 {total_cost:,.0f}₽ | 点击 {total_clicks} | "
        f"加购 {total_atbs} | 下单 {total_orders}"
    )
    
    return text


def main():
    log("=== WB广告推送开始 ===")
    
    try:
        msk_yesterday = (datetime.now(timezone.utc) - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
        
        data = get_ad_stats(msk_yesterday)
        ad_list = parse_ad_stats(data)
        report = format_report(ad_list, msk_yesterday)
        
        token = get_tenant_token()
        send_text_to_group(token, report)
        
        log("=== WB广告推送完成 ✅ ===")
        
    except Exception as e:
        log(f"❌ 失败: {e}")
        try:
            tk = get_tenant_token()
            send_text_to_group(tk, f"❌ WB广告推送失败: {str(e)[:200]}")
        except:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
