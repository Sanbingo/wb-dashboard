#!/usr/bin/env python3
"""
WB 销售日报数据生成脚本
输出 JSON 供网页版日报使用

用法:
  # 默认昨天(MSK)
  python wb-dashboard-data.py
  
  # 指定日期
  python wb-dashboard-data.py --date 2026-06-07
  
  # 输出到文件
  python wb-dashboard-data.py --output /path/to/data.json
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import WB_TOKEN_FILE, LOG_DIR
try:
    from config import WB_PROXY
except ImportError:
    WB_PROXY = None

LOG_FILE = f"{LOG_DIR}/wb-dashboard.log"


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}', file=sys.stderr)


def get_wb_token():
    with open(WB_TOKEN_FILE) as f:
        tok = json.load(f)['jwt']
    tok = tok.strip()
    return tok


def _run(cmd, timeout=30):
    """兼容Python 3.6的subprocess.run"""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        stderr = r.stderr.decode('utf-8', errors='replace') if isinstance(r.stderr, bytes) else r.stderr
        if stderr.strip():
            log(f"curl stderr: {stderr[:200]}")
        if isinstance(r.stdout, bytes):
            return r.stdout.decode('utf-8', errors='replace')
        return r.stdout
    except Exception as e:
        log(f"_run ERROR: {e}")
        return ""


def _http_request(method, url, data=None, retries=2):
    """使用 urllib 的 HTTP 请求（兼容 Python 3.6）"""
    import urllib.request
    import urllib.error
    from urllib.request import Request, urlopen
    
    token = get_wb_token()
    for attempt in range(retries + 1):
        try:
            r = Request(url, method=method)
            r.add_header('Authorization', token)
            r.add_header('Content-Type', 'application/json')
            if data is not None:
                body = json.dumps(data).encode('utf-8')
                resp = urlopen(r, data=body, timeout=25)
            else:
                resp = urlopen(r, timeout=25)
            raw = resp.read().decode('utf-8')
            if raw.strip():
                return json.loads(raw)
            return {}
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            if '429' in str(e) or 'too many' in body.lower():
                log(f"⚠️ API限流，等待30秒 (attempt {attempt+1})")
                time.sleep(30)
                continue
            log(f"HTTPError {e.code}: {body[:200]}")
            if body.strip():
                try:
                    return json.loads(body)
                except:
                    pass
            return {'error': f'HTTP {e.code}'}
        except Exception as e:
            log(f"HTTP请求失败: {e}")
            if attempt < retries:
                time.sleep(5)
                continue
            return {}
    return {}


def api_post(url, data, use_proxy=True, retries=2):
    """POST 请求 WB API"""
    return _http_request('POST', url, data, retries)


def api_get(url, use_proxy=True, retries=2):
    """GET 请求 WB API"""
    return _http_request('GET', url, None, retries)


def fetch_sales_funnel(start_date, end_date):
    """获取销售漏斗数据"""
    payload = {
        "selectedPeriod": {"start": start_date, "end": end_date},
        "limit": 100
    }
    data = api_post(
        'https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products',
        payload
    )
    products = data.get('data', {}).get('products', [])
    log(f"销售漏斗返回 {len(products)} 个商品")
    if not products:
        log(f"DEBUG response: {str(data)[:300]}")
    return products


def fetch_all_adverts():
    """获取所有广告活动及关联NM"""
    data = api_get('https://advert-api.wildberries.ru/api/advert/v2/adverts', use_proxy=False)
    adverts = data.get('adverts', [])
    log(f"广告列表返回 {len(adverts)} 个活动")

    # 构建 nmId -> 广告活动列表 映射
    nm_to_ads = {}  # nmId -> [{advertId, name, status, type}]
    for ad in adverts:
        ad_id = ad['id']
        ad_name = ad['settings']['name']
        ad_status = ad['status']
        ad_type = ad['settings']['payment_type']
        for nm_setting in ad.get('nm_settings', []):
            nm_id = nm_setting['nm_id']
            if nm_id not in nm_to_ads:
                nm_to_ads[nm_id] = []
            nm_to_ads[nm_id].append({
                'advertId': ad_id,
                'name': ad_name,
                'status': ad_status,
                'payment_type': ad_type
            })

    # 筛选活跃广告（status=11=运行中, 7=暂停中）
    active_ads = [a for a in adverts if a['status'] in (7, 11, 9)]
    return active_ads, nm_to_ads


def fetch_ad_fullstats(start_date, end_date, advert_ids):
    """获取广告活动完整统计"""
    if not advert_ids:
        return []
    ids = ','.join(str(i) for i in advert_ids)
    url = (f'https://advert-api.wildberries.ru/adv/v3/fullstats'
           f'?ids={ids}&period=day&beginDate={start_date}&endDate={end_date}')
    data = api_get(url, use_proxy=False)

    # 确保是列表
    if isinstance(data, list):
        log(f"广告统计返回 {len(data)} 个活动")
        return data
    elif isinstance(data, dict) and 'adverts' in data:
        return data['adverts']
    return []


def parse_ad_stats(fullstats_data):
    """
    从 fullstats 数据提取每个 NM 的广告花费
    返回: { nmId: { 'cost': total_sum, 'orders': total_orders, 'clicks': clicks, 'adverts': [{id, name, cost}] } }
    """
    nm_stats = {}
    for campaign in (fullstats_data or []):
        advert_id = campaign.get('advertId')
        days = campaign.get('days', [])
        for day in days:
            apps = day.get('apps', [])
            for app in apps:
                nms = app.get('nms', [])
                for nm in nms:
                    nm_id = nm.get('nmId')
                    cost = nm.get('sum', 0) or 0
                    orders = nm.get('orders', 0) or 0
                    clicks = nm.get('clicks', 0) or 0
                    views = nm.get('views', 0) or 0
                    sum_price = nm.get('sum_price', 0) or 0
                    name = nm.get('name', '')

                    if nm_id not in nm_stats:
                        nm_stats[nm_id] = {
                            'nmId': nm_id,
                            'name': name,
                            'cost': 0,
                            'orders': 0,
                            'clicks': 0,
                            'views': 0,
                            'sum_price': 0,
                            'adverts': []
                        }
                    nm_stats[nm_id]['cost'] += cost
                    nm_stats[nm_id]['orders'] += orders
                    nm_stats[nm_id]['clicks'] += clicks
                    nm_stats[nm_id]['views'] += views
                    nm_stats[nm_id]['sum_price'] += sum_price

                    # Track per-advert cost
                    found = False
                    for a in nm_stats[nm_id]['adverts']:
                        if a['advertId'] == advert_id:
                            a['cost'] += cost
                            a['orders'] += orders
                            found = True
                            break
                    if not found:
                        nm_stats[nm_id]['adverts'].append({
                            'advertId': advert_id,
                            'cost': cost,
                            'orders': orders
                        })

    return nm_stats


def merge_data(products, nm_stats, nm_to_ads, all_adverts, start_date, end_date):
    """
    合并销售数据 + 广告花费数据
    返回完整日报 JSON
    """
    total_orders = 0
    total_amount = 0
    total_buyout = 0
    total_buyout_sum = 0
    total_ad_cost = 0
    total_carts = 0
    total_views = 0
    total_profit = 0

    product_rows = []
    for p in products:
        stat = p.get('statistic', {}).get('selected', {})
        product_info = p.get('product', {})
        nm_id = product_info.get('nmId', 0)
        vendor_code = product_info.get('vendorCode', '')
        title = product_info.get('title', '') or product_info.get('name', '')

        orders = stat.get('orderCount', 0)
        amount = stat.get('orderSum', 0)
        buyout = stat.get('buyoutCount', 0)
        buyout_sum = stat.get('buyoutSum', 0)
        carts = stat.get('cartCount', 0)
        views = stat.get('openCount', 0)

        total_orders += orders
        total_amount += amount
        total_buyout += buyout
        total_buyout_sum += buyout_sum
        total_carts += carts
        total_views += views

        # 广告数据
        ad_cost = 0
        ad_orders = 0
        ad_clicks = 0
        ad_details = []
        active_campaigns = []

        if nm_id in nm_stats:
            ns = nm_stats[nm_id]
            ad_cost = ns['cost']
            ad_orders = ns['orders']
            ad_clicks = ns['clicks']
            for a in ns.get('adverts', []):
                ad_details.append({
                    'advertId': a['advertId'],
                    'cost': round(a['cost'], 2),
                    'orders': a['orders']
                })

        # 关联广告活动名称
        if nm_id in nm_to_ads:
            for ad in nm_to_ads[nm_id]:
                active_campaigns.append({
                    'advertId': ad['advertId'],
                    'name': ad['name'],
                    'status': ad['status'],
                    'payment_type': ad['payment_type']
                })

        total_ad_cost += ad_cost

        # 广告占比
        ad_ratio = round(ad_cost / amount * 100, 2) if amount > 0 else 0
        # 广告费占成交额比例
        ad_buyout_ratio = round(ad_cost / buyout_sum * 100, 2) if buyout_sum > 0 else 0

        # 净利润 = 销售额 - 广告费（实际中还需考虑成本、佣金等）
        profit = amount - ad_cost
        total_profit += profit

        product_rows.append({
            'nmId': nm_id,
            'vendorCode': vendor_code or str(nm_id),
            'title': (title or vendor_code or str(nm_id))[:50],
            'orders': orders,
            'amount': round(amount, 2),
            'buyout': buyout,
            'buyout_sum': round(buyout_sum, 2),
            'carts': carts,
            'views': views,
            'adCost': round(ad_cost, 2),
            'adOrders': ad_orders,
            'adClicks': ad_clicks,
            'adRatio': ad_ratio,
            'adBuyoutRatio': ad_buyout_ratio,
            'profit': round(profit, 2),
            'adDetails': ad_details,
            'activeCampaigns': active_campaigns
        })

    # 按广告花费降序排列
    product_rows.sort(key=lambda x: x['adCost'], reverse=True)

    # 所有活跃广告活动汇总
    all_active_ads = []
    seen_ad_ids = set()
    for p in product_rows:
        for ad in p.get('activeCampaigns', []):
            if ad['advertId'] not in seen_ad_ids:
                seen_ad_ids.add(ad['advertId'])
                all_active_ads.append(ad)

    # 按广告活动的花费汇总
    ad_campaign_summary = {}
    for p in product_rows:
        for ad_detail in p.get('adDetails', []):
            aid = ad_detail['advertId']
            if aid not in ad_campaign_summary:
                ad_campaign_summary[aid] = {'advertId': aid, 'cost': 0, 'orders': 0, 'products': []}
            ad_campaign_summary[aid]['cost'] += ad_detail['cost']
            ad_campaign_summary[aid]['orders'] += ad_detail['orders']
            if ad_detail['cost'] > 0:
                ad_campaign_summary[aid]['products'].append(p['vendorCode'])

    # 去重并排序
    ad_campaign_list = sorted(
        ad_campaign_summary.values(),
        key=lambda x: x['cost'],
        reverse=True
    )

    # 名称映射
    ad_name_map = {a['id']: a['settings']['name'] for a in all_adverts}
    for c in ad_campaign_list:
        c['name'] = ad_name_map.get(c['advertId'], f'广告{c["advertId"]}')

    report = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'reportDate': f"{start_date} ~ {end_date}" if start_date != end_date else start_date,
        'summary': {
            'totalOrders': total_orders,
            'totalAmount': round(total_amount, 2),
            'totalBuyout': total_buyout,
            'totalBuyoutSum': round(total_buyout_sum, 2),
            'totalAdCost': round(total_ad_cost, 2),
            'totalCarts': total_carts,
            'totalViews': total_views,
            'totalProfit': round(total_profit, 2),
            'adRatio': round(total_ad_cost / total_amount * 100, 2) if total_amount > 0 else 0,
            'adBuyoutRatio': round(total_ad_cost / total_buyout_sum * 100, 2) if total_buyout_sum > 0 else 0,
            'productCount': len(product_rows),
            'cartConversion': round(total_orders / total_carts * 100, 1) if total_carts > 0 else 0,
            'addToCartRate': round(total_carts / total_views * 100, 1) if total_views > 0 else 0,
            'viewConversion': round(total_orders / total_views * 100, 1) if total_views > 0 else 0,
        },
        'products': product_rows,
        'adCampaigns': ad_campaign_list,
        'activeCampaigns': all_active_ads,
    }

    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description='WB 销售日报数据生成')
    parser.add_argument('--start', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', help='结束日期 (YYYY-MM-DD)，默认同开始日期')
    parser.add_argument('--date', help='单日日期 (YYYY-MM-DD)，默认昨天MSK')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--pretty', action='store_true', default=True, help='美化输出')
    args = parser.parse_args()

    log("=== WB日报数据生成开始 ===")

    try:
        # 计算MSK日期
        now_utc = datetime.now(timezone.utc)
        if args.date:
            start_date = end_date = args.date
        elif args.start:
            start_date = args.start
            end_date = args.end if args.end else args.start
        else:
            start_date = end_date = (now_utc - timedelta(hours=5, days=1)).strftime('%Y-%m-%d')
        
        log(f"统计日期区间(MSK): {start_date} ~ {end_date}")

        # 1. 获取销售漏斗数据
        products = fetch_sales_funnel(start_date, end_date)

        # 2. 获取广告活动列表
        all_ads, nm_to_ads = fetch_all_adverts()

        # 3. 获取广告花费数据（仅查活跃活动）
        active_ids = [a['id'] for a in all_ads]
        ad_stats_data = fetch_ad_fullstats(start_date, end_date, active_ids)
        nm_stats = parse_ad_stats(ad_stats_data)
        log(f"解析到 {len(nm_stats)} 个NM有广告花费记录")

        # 4. 合并数据
        report = merge_data(products, nm_stats, nm_to_ads, all_ads, start_date, end_date)

        # 输出
        output = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
        
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or '.', exist_ok=True)
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            log(f"数据已写入: {args.output}")
        else:
            print(output)

        log(f"=== WB日报数据生成完成 ✅ ===")
        log(f"汇总: {report['summary']['totalOrders']}单, "
            f"{report['summary']['totalAmount']:,.0f}₽, "
            f"广告费{report['summary']['totalAdCost']:,.0f}₽, "
            f"占比{report['summary']['adRatio']}%")

    except Exception as e:
        log(f"❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
