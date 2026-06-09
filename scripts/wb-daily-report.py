#!/usr/bin/env python3
"""
Wildberries Daily Order Report for Feishu
修复版：使用seller-analytics-api获取销售漏斗数据（与后台统计口径一致）
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
import pytz

API_BASE = 'https://seller-analytics-api.wildberries.ru'
TOKEN_FILE = '/Users/san/.openclaw/workspace/secrets/wb-api.json'


def get_token():
    """读取WB JWT token"""
    with open(TOKEN_FILE) as f:
        return json.load(f)['jwt']


def fetch_sales_funnel(msk_date):
    """获取销售漏斗数据（与后台统计口径一致）"""
    token = get_token()
    payload = {
        "selectedPeriod": {"start": msk_date, "end": msk_date},
        "limit": 100
    }

    result = subprocess.run([
        'curl', '-s', '-X', 'POST',
        f'{API_BASE}/api/analytics/v3/sales-funnel/products',
        '-H', f'Authorization: Bearer {token}',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps(payload)
    ], capture_output=True, text=True, timeout=30)

    return json.loads(result.stdout) if result.stdout.strip() else {}


def calc_summary(products):
    """计算汇总数据"""
    total_orders = 0
    total_amount = 0
    total_buyout = 0
    total_buyout_sum = 0
    total_views = 0
    total_carts = 0

    product_list = []
    for p in products:
        stat = p.get('statistic', {}).get('selected', {})
        product_info = p.get('product', {})
        name = product_info.get('vendorCode') or product_info.get('title', '未知')
        orders = stat.get('orderCount', 0)
        amount = stat.get('orderSum', 0)
        buyout = stat.get('buyoutCount', 0)
        buyout_sum = stat.get('buyoutSum', 0)
        views = stat.get('openCount', 0)
        carts = stat.get('cartCount', 0)

        total_orders += orders
        total_amount += amount
        total_buyout += buyout
        total_buyout_sum += buyout_sum
        total_views += views
        total_carts += carts

        if orders > 0:
            product_list.append({
                'name': name,
                'nmId': product_info.get('nmId', ''),
                'orders': orders,
                'amount': amount,
                'buyout': buyout,
                'buyout_sum': buyout_sum,
                'views': views,
                'carts': carts
            })

    # 按订单数排序
    product_list.sort(key=lambda x: x['orders'], reverse=True)

    return {
        'total_orders': total_orders,
        'total_amount': round(total_amount, 0),
        'total_buyout': total_buyout,
        'total_buyout_sum': round(total_buyout_sum, 0),
        'total_views': total_views,
        'total_carts': total_carts,
        'products': product_list[:10]  # Top 10
    }


def main():
    # 使用正确的时区处理
    msk = pytz.timezone('Europe/Moscow')
    now_msk = datetime.now(timezone.utc).astimezone(msk)

    # 昨天MSK日期
    yesterday_msk = now_msk - timedelta(days=1)
    msk_date_str = yesterday_msk.strftime('%Y-%m-%d')

    print(f"当前MSK: {now_msk.strftime('%Y-%m-%d %H:%M')}")
    print(f"统计日期: {msk_date_str}")

    try:
        data = fetch_sales_funnel(msk_date_str)

        if 'data' not in data:
            print(json.dumps({
                'error': f'API返回异常: {json.dumps(data, ensure_ascii=False)[:200]}'
            }, ensure_ascii=False))
            sys.exit(1)

        products = data['data'].get('products', [])
        print(f"商品数: {len(products)}")

    except Exception as e:
        print(json.dumps({'error': str(e)}, ensure_ascii=False))
        sys.exit(1)

    # 计算汇总
    summary = calc_summary(products)

    # 生成报告
    report = {
        'generated_at': now_msk.strftime('%Y-%m-%d %H:%M'),
        'msk_date': msk_date_str,
        'summary': summary,
    }

    # 计算转化率
    cart_conversion = (summary['total_orders'] / summary['total_carts'] * 100) if summary['total_carts'] > 0 else 0
    view_conversion = (summary['total_orders'] / summary['total_views'] * 100) if summary['total_views'] > 0 else 0

    text = (
        f"📦 **Wildberries 销售日报（MSK {msk_date_str}）**\n"
        f"⏱ 生成时间：{report['generated_at']} MSK\n\n"
        f"━━━ 📊 昨日统计 ━━━\n"
        f"📋 订单数：**{summary['total_orders']} 单**\n"
        f"💰 订单金额：**{summary['total_amount']:,.0f} ₽**\n"
        f"✅ 成交数：**{summary['total_buyout']} 单**\n"
        f"🏷 成交金额：**{summary['total_buyout_sum']:,.0f} ₽**\n"
        f"👁 浏览量：**{summary['total_views']:,}**\n"
        f"🛒 加购数：**{summary['total_carts']:,}**\n"
        f"📈 加购→订单：**{cart_conversion:.1f}%**\n"
    )

    if summary['products']:
        text += "\n🏆 **热卖 Top 10**\n"
        for i, p in enumerate(summary['products'], 1):
            text += (
                f"  {i}. {p['name'][:25]} — {p['orders']}单 / "
                f"{p['amount']:,.0f}₽ (成交{p['buyout']})\n"
            )

    report['text'] = text
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
