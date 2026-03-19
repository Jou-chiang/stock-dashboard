"""
台股即時股價抓取腳本
讀取 stocks.json 取得股票清單，三重回補邏輯抓取最新價格
由 GitHub Actions 每 5 分鐘執行一次（台北時間盤中）
"""

import requests
import json
from datetime import datetime, timezone, timedelta

def now_tw():
    return datetime.now(timezone(timedelta(hours=8)))

def load_stocks():
    try:
        with open('stocks.json', 'r', encoding='utf-8') as f:
            stocks = json.load(f)
        print(f'載入 {len(stocks)} 支股票: {[s["id"] for s in stocks]}')
        return stocks
    except Exception as e:
        print(f'讀取 stocks.json 失敗: {e}')
        return []

def fetch_twse(stock_ids, market='tse'):
    stock_query = '|'.join([f'{market}_{s}.tw' for s in stock_ids])
    url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={stock_query}&json=1&delay=0'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/fibest.jsp'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return r.json().get('msgArray', [])
    except Exception as e:
        print(f'  API 錯誤 ({market}): {e}')
        return []

def parse_stock(m, name_override=''):
    """
    三重回補邏輯：
    z（成交價）→ b（買進五檔第一筆）→ a（賣出五檔第一筆）→ y（昨收保底）
    """
    try:
        def valid(v): return v and v not in ['-', '', None]

        z = m.get('z', '')
        b = m.get('b', '')
        a = m.get('a', '')
        y = m.get('y', '')

        z_val = z if valid(z) else None
        b_val = b.split('_')[0] if valid(b) else None
        a_val = a.split('_')[0] if valid(a) else None
        y_val = y if valid(y) else None

        current = z_val or b_val or a_val or y_val
        if not current:
            return None

        price    = float(current)
        prev     = float(y_val) if y_val else None
        chg      = round((price - prev) / prev * 100, 2) if prev and prev > 0 else None
        is_rt    = z_val is not None

        vol_str  = m.get('v', '0')
        vol      = int(float(vol_str)) if valid(vol_str) else 0
        h        = float(m.get('h') or 0) or None
        l        = float(m.get('l') or 0) or None
        name     = m.get('n', '') or name_override

        tag = '●即時' if is_rt else '○回補'
        chg_str = f'({chg:+.2f}%)' if chg is not None else ''
        print(f'  {tag} {m.get("c","")} {name}: {price} {chg_str}')

        return {
            'id':          m.get('c', ''),
            'name':        name,
            'price':       round(price, 2),
            'prev_close':  round(prev, 2) if prev else None,
            'change_pct':  chg,
            'high':        h,
            'low':         l,
            'vol':         vol,
            'is_realtime': is_rt,
        }
    except Exception as e:
        print(f'  解析錯誤 {m.get("c","?")}: {e}')
        return None

def main():
    t = now_tw()
    print(f'=== 股價更新 {t.strftime("%H:%M")} 台北時間 ===')

    stocks = load_stocks()
    if not stocks:
        return

    stock_ids = [s['id'] for s in stocks]
    name_map  = {s['id']: s['name'] for s in stocks}

    result_map = {}
    for m in fetch_twse(stock_ids, 'tse'):
        sid = m.get('c', '').strip()
        if sid:
            parsed = parse_stock(m, name_map.get(sid, ''))
            if parsed:
                result_map[sid] = parsed

    missing = [sid for sid in stock_ids if sid not in result_map]
    if missing:
        print(f'改試 OTC: {missing}')
        for m in fetch_twse(missing, 'otc'):
            sid = m.get('c', '').strip()
            if sid:
                parsed = parse_stock(m, name_map.get(sid, ''))
                if parsed:
                    result_map[sid] = parsed

    results = []
    for s in stocks:
        sid = s['id']
        if sid in result_map:
            results.append(result_map[sid])
        else:
            print(f'  ✗ {sid} {s["name"]}: 無資料')
            results.append({
                'id': sid, 'name': s['name'],
                'price': None, 'prev_close': None,
                'change_pct': None, 'high': None,
                'low': None, 'vol': 0,
                'is_realtime': False,
            })

    output = {
        'updated_at':    datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'updated_at_tw': t.strftime('%H:%M'),
        'prices':        results
    }
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    rt = sum(1 for r in results if r['is_realtime'])
    print(f'\n✅ 完成！{rt}/{len(results)} 支即時，已存入 prices.json')

if __name__ == '__main__':
    main()
