#!/usr/bin/env python3
"""
WB 店铺销售日报脚本
每天08:00 由系统cron执行
1. 调用WB卖家分析API获取昨日销售数据
2. 汇总统计
3. 发送到飞书群聊
"""
import json
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LOG_DIR, WB_PROXY
from lib.feishu import get_tenant_token, send_text_to_group

LOG_FILE = f"{LOG_DIR}/wb-sales-daily.log"


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}')


def get_wb_token():
    """读WB JWT"""
    with open(os.path.expanduser('~/.openclaw/workspace/secrets/wb-api.json')) as f:
        return json.load(f)['jwt']


def get_sales_data(msk_date):
    """调用卖家分析API获取昨日销售漏斗数据"""
    token = get_wb_token()
    payload = {
        "selectedPeriod": {"start": msk_date, "end": msk_date},
        "limit": 100
    }
    
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', '-x', WB_PROXY,
         'https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products',
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload)],
        capture_output=True, text=True, timeout=30
    )
    
    data = json.loads(r.stdout) if r.stdout.strip() else {}
    log(f"API返回商品数: {len(data.get('data', {}).get('products', []))}")
    return data


def format_report(data, msk_date):
    """格式化为飞书消息"""
    products = data.get('data', {}).get('products', [])
    
    total_orders = 0
    total_amount = 0
    total_buyout = 0
    total_buyout_sum = 0
    
    lines = []
    for p in (products or [])[:10]:  # 最多显示10个
        stat = p.get('statistic', {}).get('selected', {})
        name = p.get('vendorCode', p.get('nmId', '未知'))
        orders = stat.get('orderCount', 0)
        amount = stat.get('orderSum', 0)
        buyout = stat.get('buyoutCount', 0)
        buyout_sum = stat.get('buyoutSum', 0)
        
        total_orders += orders
        total_amount += amount
        total_buyout += buyout
        total_buyout_sum += buyout_sum
        
        if orders > 0:
            lines.append(
                f"• {name[:20]}: {orders}单 / {amount:,.0f}₽ "
                f"(成交{buyout}/{buyout_sum:,.0f}₽)"
            )
    
    text = (
        f"📊 WB昨日销售日报（MSK {msk_date}）\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📋 总订单：{total_orders} 单\n"
        f"💰 总金额：{total_amount:,.0f} ₽\n"
        f"✅ 成交：{total_buyout} 单 / {total_buyout_sum:,.0f} ₽\n"
    )
    
    if lines:
        text += f"\n📦 商品明细（Top {min(len(lines), 10)}）：\n"
        text += '\n'.join(lines)
    
    return text


def main():
    log("=== WB销售日报开始 ===")
    
    try:
        # MSK昨天
        msk_yesterday = (datetime.now(timezone.utc) - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
        
        data = get_sales_data(msk_yesterday)
        report = format_report(data, msk_yesterday)
        
        # 发送到飞书群
        token = get_tenant_token()
        send_text_to_group(token, report)
        
        log(f"=== WB销售日报完成 ✅ ===")
        
    except Exception as e:
        log(f"❌ 失败: {e}")
        try:
            tk = get_tenant_token()
            send_text_to_group(tk, f"❌ WB销售日报执行失败: {str(e)[:200]}")
        except:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
