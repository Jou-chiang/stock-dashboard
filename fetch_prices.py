"""
台股股價 + 歷史K線抓取腳本
- 即時股價：TWSE MIS API（三重回補）
- 歷史K線：TWSE/TPEX 月份資料（供前端計算 KDJ/RSI/DIF）
- 讀取 stocks.json，存入 prices.json
- GitHub Actions 每分鐘執行（台北時間盤中）
"""

import requests
import json
import time
from datetime import datetime, timedelta
import pytz

tw_tz = pytz.timezone('Asia/Taipei')

def now_tw():
    return datetime.now(tw_tz)

def load_stocks():
    try:
        with open('stocks.json', 'r', encoding='utf-8') as f:
            stocks = json.load(f)
        print(f'載入 {len(stocks)} 支股票: {[s["id"] for s in stocks]}')
        return stocks
    except Exception as e:
        print(f'讀取 stocks.json 失敗: {e}')
        return []

# ── 即時股價 ────────────────────────────────────────────
def fetch_realtime(stock_ids, market='tse'):
    stock_query = '|'.join([f'{market}_{s}.tw' for s in stock_ids])
    url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={stock_query}&json=1&delay=0'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/fibest.jsp'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return r.json().get('msgArray', [])
    except Exception as e:
        print(f'  即時API錯誤 ({market}): {e}')
        return []

def parse_realtime(m, name_override=''):
    try:
        def valid(v): return v and v not in ['-', '', None]
        z = m.get('z'); b = m.get('b', ''); a = m.get('a', ''); y = m.get('y', '-')
        z_val = z if valid(z) else None
        b_val = b.split('_')[0] if valid(b) else None
        a_val = a.split('_')[0] if valid(a) else None
        y_val = y if valid(y) else None
        current = z_val or b_val or a_val or y_val
        if not current: return None
        price = float(current)
        prev  = float(y_val) if y_val else None
        chg   = round((price - prev) / prev * 100, 2) if prev and prev > 0 else None
        vol_str = m.get('v', '0')
        vol = int(float(vol_str)) if valid(vol_str) else 0
        is_rt = z_val is not None
        tag = '●即時' if is_rt else '○回補'
        name = m.get('n', '') or name_override
        print(f'  {tag} {m.get("c","")} {name}: {price}' + (f' ({chg:+.2f}%)' if chg else ''))
        return {
            'id': m.get('c', ''), 'name': name,
            'price': round(price, 2), 'prev_close': round(prev, 2) if prev else None,
            'change_pct': chg, 'high': float(m.get('h') or 0) or None,
            'low': float(m.get('l') or 0) or None, 'vol': vol, 'is_realtime': is_rt,
        }
    except Exception as e:
        print(f'  解析錯誤 {m.get("c","?")}: {e}')
        return None

# ── 歷史K線 ─────────────────────────────────────────────
def fetch_history_twse(sym, months=4):
    """抓取上市股票歷史月K線資料"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    now = now_tw()
    for i in range(months):
        d = now - timedelta(days=i*30)
        yyyymmdd = d.strftime('%Y%m01')
        url = f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={yyyymmdd}&stockNo={sym}'
        try:
            r = requests.get(url, headers=headers, timeout=10)
            j = r.json()
            if j.get('stat') == 'OK' and j.get('data'):
                for row in j['data']:
                    # row: [民國日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌, 筆數]
                    try:
                        parts = row[0].split('/')
                        year = int(parts[0]) + 1911
                        iso_date = f'{year}-{parts[1]}-{parts[2]}'
                        close = float(row[6].replace(',', ''))
                        high  = float(row[4].replace(',', ''))
                        low   = float(row[5].replace(',', ''))
                        vol   = float(row[1].replace(',', ''))  # 股數
                        if close > 0:
                            results.append({
                                'date': iso_date, 'close': close,
                                'max': high, 'min': low,
                                'Trading_Volume': vol
                            })
                    except: pass
        except Exception as e:
            print(f'  歷史TWSE {sym} {yyyymmdd}: {e}')
        time.sleep(0.3)  # 避免太快被擋
    return sorted(results, key=lambda r: r['date'])

def fetch_history_tpex(sym, months=4):
    """抓取上櫃股票歷史月K線資料"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    now = now_tw()
    for i in range(months):
        d = now - timedelta(days=i*30)
        yy = d.year - 1911
        mm = d.strftime('%m')
        url = f'https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d={yy}/{mm}&s={sym}&o=json'
        try:
            r = requests.get(url, headers=headers, timeout=10)
            j = r.json()
            if j.get('iTotalRecords', 0) > 0 and j.get('aaData'):
                for row in j['aaData']:
                    try:
                        parts = row[0].split('/')
                        year = int(parts[0]) + 1911
                        iso_date = f'{year}-{parts[1]}-{parts[2]}'
                        close = float(row[6].replace(',', ''))
                        high  = float(row[4].replace(',', ''))
                        low   = float(row[5].replace(',', ''))
                        vol   = float(row[1].replace(',', ''))
                        if close > 0:
                            results.append({
                                'date': iso_date, 'close': close,
                                'max': high, 'min': low,
                                'Trading_Volume': vol
                            })
                    except: pass
        except Exception as e:
            print(f'  歷史TPEX {sym} {yy}/{mm}: {e}')
        time.sleep(0.3)
    return sorted(results, key=lambda r: r['date'])

def fetch_history(sym, months=4):
    """先試上市，失敗再試上櫃"""
    rows = fetch_history_twse(sym, months)
    if len(rows) >= 20:
        print(f'  歷史資料 {sym}: {len(rows)} 筆（上市）')
        return rows
    rows = fetch_history_tpex(sym, months)
    if len(rows) >= 20:
        print(f'  歷史資料 {sym}: {len(rows)} 筆（上櫃）')
        return rows
    print(f'  歷史資料 {sym}: 不足（{len(rows)} 筆）')
    return rows

# ── 主程式 ──────────────────────────────────────────────
def main():
    t = now_tw()
    print(f'=== 更新 {t.strftime("%Y-%m-%d %H:%M:%S")} 台北時間 ===')

    stocks = load_stocks()
    if not stocks:
        print('沒有股票清單，結束')
        return

    stock_ids = [s['id'] for s in stocks]
    name_map  = {s['id']: s['name'] for s in stocks}

    # Step 1：抓即時股價
    print('\n── 即時股價 ──')
    rt_map = {}
    for m in fetch_realtime(stock_ids, 'tse'):
        sid = m.get('c', '').strip()
        if sid:
            parsed = parse_realtime(m, name_map.get(sid, ''))
            if parsed: rt_map[sid] = parsed

    missing = [sid for sid in stock_ids if sid not in rt_map]
    if missing:
        print(f'改試 OTC: {missing}')
        for m in fetch_realtime(missing, 'otc'):
            sid = m.get('c', '').strip()
            if sid:
                parsed = parse_realtime(m, name_map.get(sid, ''))
                if parsed: rt_map[sid] = parsed

    # Step 2：抓歷史K線（只在每小時整點或第一次跑時更新，節省時間）
    # 讀取舊的 prices.json 看歷史資料多久沒更新
    try:
        with open('prices.json', 'r', encoding='utf-8') as f:
            old_data = json.load(f)
        old_hist_at = old_data.get('history_updated_at', '')
        need_history = not old_hist_at or (t - datetime.fromisoformat(old_hist_at.replace('Z','')). \
            replace(tzinfo=pytz.utc)).total_seconds() > 3600
    except:
        need_history = True
        old_data = {}

    if need_history:
        print('\n── 歷史K線（每小時更新）──')
        history_map = {}
        for s in stocks:
            sid = s['id']
            rows = fetch_history(sid)
            if rows:
                history_map[sid] = rows
        print(f'歷史資料更新完成')
    else:
        print(f'\n歷史資料未到更新時間，沿用舊資料')
        history_map = {p['id']: p.get('history', []) for p in old_data.get('prices', [])}

    # Step 3：整合結果
    results = []
    for s in stocks:
        sid = s['id']
        rt = rt_map.get(sid, {})
        hist = history_map.get(sid, [])
        results.append({
            'id':          sid,
            'name':        rt.get('name') or s['name'],
            'price':       rt.get('price'),
            'prev_close':  rt.get('prev_close'),
            'change_pct':  rt.get('change_pct'),
            'high':        rt.get('high'),
            'low':         rt.get('low'),
            'vol':         rt.get('vol', 0),
            'is_realtime': rt.get('is_realtime', False),
            'history':     hist,  # 歷史K線資料
        })

    output = {
        'updated_at':        datetime.now(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'updated_at_tw':     t.strftime('%H:%M'),
        'history_updated_at': datetime.now(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if need_history else old_hist_at,
        'prices':            results
    }
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    rt_count = sum(1 for r in results if r['is_realtime'])
    hist_count = sum(1 for r in results if r.get('history'))
    print(f'\n✅ 完成！即時{rt_count}/{len(results)}支，歷史{hist_count}/{len(results)}支')

if __name__ == '__main__':
    main()
