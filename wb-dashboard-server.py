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
import io
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

PROTECTED_PATHS = ['/wb-dashboard.html', '/wb-settings.html', '/wb-inventory.html', '/wb-booking.html', '/api/wb-daily', '/api/mappings', '/api/wb-offices', '/api/send-feishu', '/api/warehouses', '/api/tasks', '/api/wb-inventory', '/api/wb-inventory-sizes']

COST_PRICE_FILE = os.path.join(DATA_DIR, 'cost-prices.json')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.json')


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
        elif path == '/api/wb-inventory':
            self.handle_wb_inventory()
        elif path == '/api/wb-inventory-sizes':
            self.handle_wb_inventory_sizes(params)
        elif path == '/api/cost-price':
            self.handle_get_cost_prices()
        elif path == '/api/wb-offices':
            self.handle_wb_offices()
        elif path == '/api/warehouses':
            self.handle_get_warehouses()
        elif path == '/api/tasks':
            self.handle_get_tasks()
        elif path == '/api/mappings':
            self.handle_get_mappings()
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
            start = end = (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))) - timedelta(days=1)).strftime('%Y-%m-%d')
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
        elif path == '/api/cost-price':
            if not self.require_auth():
                self.send_json({'error': 'unauthorized'}, 401)
                return
            self.handle_save_cost_price()
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
    
    def handle_wb_inventory(self):
        """获取WB库存数据（含多周期日均订单、断货预测）"""
        import urllib.request
        import ssl
        import time as _time
        
        try:
            # 0. 获取JWT token
            config_path = os.path.join(WORKSPACE, 'config.py')
            cfg_globals = {}
            with open(config_path) as f:
                exec(f.read(), cfg_globals)
            token_file = cfg_globals.get('WB_TOKEN_FILE', '/opt/wb-scripts/secrets/wb-api.json')
            with open(token_file) as f:
                cfg = json.load(f)
            token = cfg['jwt'].strip()
            
            ctx = ssl._create_unverified_context()
            msk_tz = timezone(timedelta(hours=3))
            today = datetime.now(timezone.utc).astimezone(msk_tz)
            today_str = today.strftime('%Y-%m-%d')
            
            # 加载成本价
            cost_prices = {}
            if os.path.exists(COST_PRICE_FILE):
                try:
                    with open(COST_PRICE_FILE, 'r', encoding='utf-8') as f:
                        cost_prices = json.load(f)
                except:
                    pass
            
            # 检查缓存（1小时有效）
            inventory_cache_file = os.path.join(DATA_DIR, 'inventory-full-cache.json')
            if os.path.exists(inventory_cache_file):
                try:
                    with open(inventory_cache_file, 'r') as f:
                        cache_data = json.load(f)
                    cache_time = cache_data.get('_cachedAt', 0)
                    if time.time() - cache_time < 3600:  # 1小时缓存
                        for p in cache_data.get('products', []):
                            p['costPrice'] = cost_prices.get(str(p['nmId']), 0)
                        self.send_json(cache_data)
                        return
                except:
                    pass
            
            # 加载中文映射
            mappings_path = os.path.join(DATA_DIR, 'mappings.json')
            mappings = {}
            if os.path.exists(mappings_path):
                try:
                    with open(mappings_path, 'r', encoding='utf-8') as f:
                        mappings = json.load(f)
                except:
                    pass
            # 备货天数（从采购到入库的周期）
            LEAD_TIME_DAYS = 25
            
            api_base = 'https://seller-analytics-api.wildberries.ru'
            
            # 获取三个时间段的订单数据
            periods = {
                '7d': (timedelta(days=6), timedelta(days=0)),
                '15d': (timedelta(days=14), timedelta(days=0)),
                '30d': (timedelta(days=29), timedelta(days=0)),
            }
            
            # 用于存储各周期订单数
            orders_by_period = {}
            products_data = {}
            
            for period_name, (delta_start, delta_end) in periods.items():
                start_str = (today - delta_start).strftime('%Y-%m-%d')
                end_str = (today - delta_end).strftime('%Y-%m-%d')
                
                payload = json.dumps({
                    'currentPeriod': {'start': start_str, 'end': end_str},
                    'stockType': '',
                    'skipDeletedNm': False,
                    'offset': 0,
                    'availabilityFilters': ['deficient','actual','balanced','nonActual','nonLiquid','invalidData'],
                    'orderBy': {'field': 'ordersCount', 'mode': 'desc'}
                }).encode()
                
                # 带重试的API调用
                for retry in range(3):
                    try:
                        req = urllib.request.Request(
                            api_base + '/api/v2/stocks-report/products/products',
                            method='POST', data=payload)
                        req.add_header('Authorization', token)
                        req.add_header('Content-Type', 'application/json')
                        resp = urllib.request.urlopen(req, timeout=20, context=ctx)
                        break
                    except urllib.error.HTTPError as _e:
                        if _e.code == 429 and retry < 2:
                            print('[WARN] Rate limited, waiting 5s...', flush=True)
                            _time.sleep(5)
                        else:
                            raise
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('data', {}).get('items', [])
                
                orders_by_period[period_name] = {}
                for item in items:
                    nm_id = item['nmID']
                    orders_by_period[period_name][nm_id] = item.get('metrics', {}).get('ordersCount', 0)
                    
                    # 第一次（7天）时创建产品数据
                    if period_name == '7d':
                        vc = item.get('vendorCode', str(nm_id))
                        cn = mappings.get(vc, '')
                        m = item.get('metrics', {})
                        cp = m.get('currentPrice', {})
                        turn = m.get('avgStockTurnover', {})
                        products_data[nm_id] = {
                            'nmId': nm_id,
                            'vendorCode': vc,
                            'title': vc,
                            'chineseName': cn,
                            'displayName': cn or vc,
                            'sizes': [],
                            'totalQty': m.get('stockCount', 0),
                            'price': cp.get('minPrice', 0),
                            'discount': 0,
                            'displayPrice': cp.get('minPrice', 0),
                            'costPrice': cost_prices.get(str(nm_id), 0),
                            'orders7d': 0, 'orders15d': 0, 'orders30d': 0,
                            'weightedAvgOrders': 0,
                            'turnoverDays': 0,
                            'predictedStockoutDate': '',
                            'predictedReorderDate': '',
                            'normalRestockQty': 0,
                            'peakRestockQty': 0,
                            'predictedRestockQty': 0,
                            'lowStock': False,
                            'canSellDays': 0
                        }
                
                _time.sleep(3)  # 避免限流（15d和30d各等3秒）
            
            # 计算加权日均订单和断货预测
            current_month = today.month
            # 4月-8月（平季）：<25天 = 低库存；9月-3月（旺季）：<45天
            is_peak_season = current_month >= 9 or current_month <= 3
            low_stock_threshold = 25 if not is_peak_season else 45
            peak_multiplier = 2.0 if is_peak_season else 1.0
            
            for nm_id, p in products_data.items():
                orders_7d = orders_by_period.get('7d', {}).get(nm_id, 0)
                orders_15d = orders_by_period.get('15d', {}).get(nm_id, 0)
                orders_30d = orders_by_period.get('30d', {}).get(nm_id, 0)
                
                p['orders7d'] = orders_7d
                p['orders15d'] = orders_15d
                p['orders30d'] = orders_30d
                
                # 加权日均订单量 = (7d/7)*0.4 + (15d/15)*0.3 + (30d/30)*0.3
                avg_7d = orders_7d / 7.0 if orders_7d > 0 else 0
                avg_15d = orders_15d / 15.0 if orders_15d > 0 else 0
                avg_30d = orders_30d / 30.0 if orders_30d > 0 else 0
                weighted_avg = avg_7d * 0.4 + avg_15d * 0.3 + avg_30d * 0.3
                p['weightedAvgOrders'] = round(weighted_avg, 2)
                
                if weighted_avg > 0 and p['totalQty'] > 0:
                    turnover_days = p['totalQty'] / weighted_avg
                    p['turnoverDays'] = round(turnover_days, 1)
                    
                    # 预计可销售天数 = 库存供应天数 - 备货天数
                    can_sell = turnover_days - LEAD_TIME_DAYS
                    p['canSellDays'] = round(can_sell, 1)
                    
                    # 预计断货日期 = 今天 + 库存供应天数
                    from datetime import datetime as _dt, timedelta as _td
                    stockout_date = today + _td(days=int(turnover_days))
                    p['predictedStockoutDate'] = stockout_date.strftime('%m-%d')
                    
                    # 预计下单补货日期 = 今天 + (库存供应天数 - 备货天数)
                    reorder_days = int(turnover_days - LEAD_TIME_DAYS)
                    if reorder_days <= 0:
                        p['predictedReorderDate'] = '立即下单'
                    else:
                        reorder_date = today + _td(days=reorder_days)
                        p['predictedReorderDate'] = reorder_date.strftime('%m-%d')
                    
                    # 日常补货量 = 备货天数 * 日均订单（旺季x2）
                    normal_restock = LEAD_TIME_DAYS * weighted_avg
                    season_restock = normal_restock * peak_multiplier
                    p['normalRestockQty'] = round(normal_restock, 1)
                    p['peakRestockQty'] = round(season_restock, 1)
                    p['predictedRestockQty'] = round(season_restock, 1)  # 当前推荐的补货量
                    
                    # 标记低库存
                    p['lowStock'] = turnover_days < low_stock_threshold
                else:
                    p['turnoverDays'] = 0
                    p['canSellDays'] = 0
                    p['predictedStockoutDate'] = ''
                    p['predictedReorderDate'] = ''
                    p['normalRestockQty'] = 0
                    p['peakRestockQty'] = 0
                    p['predictedRestockQty'] = 0
                    p['lowStock'] = False
            
            # 排序
            product_list = sorted(products_data.values(), key=lambda x: x['totalQty'], reverse=True)
            
            result = {
                'date': today_str,
                'source': 'stocks-report',
                'totalProducts': len(product_list),
                'totalQty': sum(p['totalQty'] for p in product_list),
                'products': product_list
            }
            
            # 写缓存
            try:
                cache_data = dict(result)
                cache_data['_cachedAt'] = time.time()
                with open(inventory_cache_file, 'w') as f:
                    json.dump(cache_data, f, ensure_ascii=False)
            except:
                pass
            
            self.send_json(result)
            
        except Exception as e:
            import traceback
            err_msg = str(e)
            tb = traceback.format_exc()
            print('[ERROR] handle_wb_inventory: %s' % err_msg, flush=True)
            print(tb, flush=True)
            self.send_json({'error': err_msg, 'traceback': tb}, 500)

    def handle_wb_inventory_sizes(self, params):
        """按需获取某个商品的尺码明细"""
        import urllib.request
        import ssl
        
        try:
            nm_id = params.get('nmId', [None])[0]
            if not nm_id:
                self.send_json({'error': 'nmId required'}, 400)
                return
            
            config_path = os.path.join(WORKSPACE, 'config.py')
            cfg_globals = {}
            with open(config_path) as f:
                exec(f.read(), cfg_globals)
            token_file = cfg_globals.get('WB_TOKEN_FILE', '/opt/wb-scripts/secrets/wb-api.json')
            with open(token_file) as f:
                cfg = json.load(f)
            token = cfg['jwt'].strip()
            
            ctx = ssl._create_unverified_context()
            msk_tz = timezone(timedelta(hours=3))
            today = datetime.now(timezone.utc).astimezone(msk_tz).strftime('%Y-%m-%d')
            seven_days_ago = (datetime.now(timezone.utc).astimezone(msk_tz) - timedelta(days=6)).strftime('%Y-%m-%d')
            
            payload = json.dumps({
                'nmID': int(nm_id),
                'currentPeriod': {'start': seven_days_ago, 'end': today},
                'stockType': '',
                'includeOffice': True,
                'orderBy': {'field': 'ordersCount', 'mode': 'desc'}
            }).encode()
            
            req = urllib.request.Request(
                'https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/sizes',
                method='POST', data=payload)
            req.add_header('Authorization', token)
            req.add_header('Content-Type', 'application/json')
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            sizes_data = json.loads(resp.read().decode('utf-8'))
            
            sizes = []
            for size_item in sizes_data.get('data', {}).get('sizes', []):
                size_name = size_item.get('name', '均码')
                offices = size_item.get('offices', [])
                total_qty = sum(o.get('metrics', {}).get('stockCount', 0) for o in offices)
                
                # 计算尺码级别订单/日均数据
                total_orders = sum(o.get('metrics', {}).get('ordersCount', 0) for o in offices)
                total_avg = sum(o.get('metrics', {}).get('avgOrders', 0) for o in offices)
                turnover_days = round(total_qty / total_avg, 1) if total_avg > 0 else 0
                
                if total_qty == 0:
                    continue
                
                warehouses = []
                for off in offices:
                    off_m = off.get('metrics', {})
                    off_qty = off_m.get('stockCount', 0)
                    if off_qty > 0:
                        warehouses.append({
                            'name': off.get('officeName', '未知'),
                            'quantity': off_qty
                        })
                
                sizes.append({
                    'techSize': size_name,
                    'totalQty': total_qty,
                    'ordersCount': total_orders,
                    'avgOrders': round(total_avg, 2),
                    'turnoverDays': turnover_days,
                    'warehouses': warehouses
                })
            
            self.send_json({'nmId': int(nm_id), 'sizes': sizes})
        except urllib.error.HTTPError as e:
            self.send_json({'error': 'API error: ' + str(e.code)}, 500)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def _generate_from_stocks(self, token, ctx, today, cache_file):
        """使用 stocks API（备用）"""
        import urllib.request
        import ssl
        
        url = f'https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom={today}'
        req = urllib.request.Request(url, method='GET')
        req.add_header('Authorization', token)
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        raw_data = json.loads(resp.read().decode('utf-8'))
        
        mappings_path = os.path.join(DATA_DIR, 'mappings.json')
        mappings = {}
        if os.path.exists(mappings_path):
            try:
                with open(mappings_path, 'r', encoding='utf-8') as f:
                    mappings = json.load(f)
            except:
                pass
        
        products = {}
        for item in raw_data:
            nm_id = item['nmId']
            if nm_id not in products:
                vc = item.get('supplierArticle', str(nm_id))
                cn = mappings.get(vc, '')
                products[nm_id] = {
                    'nmId': nm_id,
                    'vendorCode': vc,
                    'title': vc,
                    'chineseName': cn,
                    'displayName': cn or vc,
                    'sizes': [],
                    'totalQty': 0,
                    'price': item.get('Price', 0),
                    'discount': item.get('Discount', 0),
                    'displayPrice': round(item.get('Price', 0) * (100 - item.get('Discount', 0)) / 100, 2),
                    'costPrice': 0
                }
            
            p = products[nm_id]
            ts = item.get('techSize', '均码')
            qty_full = item.get('quantityFull', 0)
            wh = item.get('warehouseName', '未知')
            
            if qty_full == 0:
                continue
            
            size_entry = None
            for s in p['sizes']:
                if s['techSize'] == ts:
                    size_entry = s
                    break
            if not size_entry:
                size_entry = {'techSize': ts, 'totalQty': 0, 'warehouses': []}
                p['sizes'].append(size_entry)
            
            size_entry['totalQty'] += qty_full
            p['totalQty'] += qty_full
            size_entry['warehouses'].append({
                'name': wh,
                'quantity': item.get('quantity', 0),
                'quantityFull': qty_full
            })
        
        product_list = sorted(products.values(), key=lambda x: x['totalQty'], reverse=True)
        result = {
            'date': today,
            'source': 'stocks-api',
            'totalProducts': len(product_list),
            'totalQty': sum(p['totalQty'] for p in product_list),
            'products': product_list
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except:
            pass
        
        return result
    

    
    def handle_get_cost_prices(self):
        """获取所有成本价配置"""
        if os.path.exists(COST_PRICE_FILE):
            try:
                with open(COST_PRICE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json(data)
                return
            except:
                pass
        self.send_json({})
    
    def handle_save_cost_price(self):
        """保存某个商品的成本价"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            nm_id = data.get('nmId')
            cost_price = data.get('costPrice', 0)
            
            if not nm_id:
                self.send_json({'error': 'nmId required'}, 400)
                return
            
            # 读取现有数据
            cost_prices = {}
            if os.path.exists(COST_PRICE_FILE):
                try:
                    with open(COST_PRICE_FILE, 'r', encoding='utf-8') as f:
                        cost_prices = json.load(f)
                except:
                    pass
            
            if cost_price is None or cost_price == '':
                cost_prices.pop(str(nm_id), None)
            else:
                cost_prices[str(nm_id)] = float(cost_price)
            
            with open(COST_PRICE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cost_prices, f, ensure_ascii=False, indent=2)
            
            self.send_json({'status': 'ok'})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
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
            config_path = os.path.join(WORKSPACE, 'config.py')
            cfg_globals = {}
            with open(config_path) as f:
                exec(f.read(), cfg_globals)
            token_file = cfg_globals.get('WB_TOKEN_FILE', '/opt/wb-scripts/secrets/wb-api.json')
            with open(token_file) as f:
                cfg = json.load(f)
            token = cfg['jwt'].strip()
            ctx = _ssl._create_unverified_context()
            req = urllib.request.Request(
                'https://marketplace-api.wildberries.ru/api/v3/offices', method='GET')
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
            msg_data = {
                'msg_type': 'interactive',
                'card': {
                    'header': {'title': {'tag': 'plain_text', 'content': title}, 'template': 'blue'},
                    'elements': [{'tag': 'markdown', 'content': content}]
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
    
    def handle_get_tasks(self):
        """获取定时任务列表"""
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.send_json(data)
                return
            except:
                pass
        self.send_json({'tasks': []})
    
    def handle_create_task(self):
        """创建定时任务"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            tasks_data = {'tasks': []}
            if os.path.exists(TASKS_FILE):
                try:
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks_data = json.load(f)
                except:
                    pass
            new_warehouses = sorted(data.get('warehouses', []))
            new_date = data.get('date', '')
            for t in tasks_data.get('tasks', []):
                if t.get('date') == new_date and sorted(t.get('warehouses', [])) == new_warehouses:
                    self.send_json({'status': 'duplicate', 'task': t})
                    return
            task = {
                'id': str(uuid.uuid4())[:8],
                'warehouses': data.get('warehouses', []),
                'warehouseNames': data.get('warehouseNames', []),
                'date': new_date,
                'deliveryType': data.get('deliveryType', '箱子'),
                'enabled': True,
                'createdAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'lastRunAt': None,
            }
            tasks_data['tasks'].append(task)
            with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
            self.send_json({'status': 'ok', 'task': task})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        if not self.require_auth():
            self.send_json({'error': 'unauthorized'}, 401)
            return
        if path == '/api/tasks':
            task_id = params.get('id', [None])[0]
            if not task_id:
                self.send_json({'error': 'task id required'}, 400)
                return
            try:
                tasks_data = {'tasks': []}
                if os.path.exists(TASKS_FILE):
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks_data = json.load(f)
                tasks_data['tasks'] = [t for t in tasks_data.get('tasks', []) if t.get('id') != task_id]
                with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks_data, f, ensure_ascii=False, indent=2)
                self.send_json({'status': 'ok'})
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
        else:
            self.send_error(404)
    
    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self.require_auth():
            self.send_json({'error': 'unauthorized'}, 401)
            return
        if path == '/api/tasks':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                action = data.get('action', '')
                task_id = data.get('id', '')
                if not task_id:
                    self.send_json({'error': 'task id required'}, 400)
                    return
                tasks_data = {'tasks': []}
                if os.path.exists(TASKS_FILE):
                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        tasks_data = json.load(f)
                for t in tasks_data.get('tasks', []):
                    if t.get('id') == task_id:
                        if action == 'enable':
                            t['enabled'] = True
                        elif action == 'disable':
                            t['enabled'] = False
                        elif action == 'delete':
                            tasks_data['tasks'].remove(t)
                        break
                with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks_data, f, ensure_ascii=False, indent=2)
                self.send_json({'status': 'ok'})
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
        else:
            self.send_error(404)
    
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
            parts = ' '.join(str(a) for a in args)
            print(f'[{ts}] {parts}')
        else:
            print(f'[{ts}] {format}')


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
