"""
台股即時股價抓取腳本
讀取 stocks.json 取得股票清單，抓取即時價格後存成 prices.json
由 GitHub Actions 每 5 分鐘執行一次（台北時間盤中）

要新增/刪除股票：只需修改 stocks.json，不需要改這個腳本
"""

import requests
import json
import time
from datetime import datetime

def load_stocks():
    try:
        with open('stocks.json', 'r', encoding='utf-8') as f:
            stocks = json.load(f)
        print(f'載入 {len(stocks)} 支股票: {[s["id"] for s in stocks]}')
        return stocks
    except Exception as e:
        print(f'讀取 stocks.json 失敗: {e}')
        return []

def fetch_prices(stock_ids, market='tse'):
    ex_ch = '|'.join([f'{market}_{sid}.tw' for sid in stock_ids])
    url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&_={int(time.time()*1000)}'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/fibest.jsp'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return r.json().get('msgArray', [])
    except Exception as e:
        print(f'  API 錯誤 ({market}): {e}')
        return []

def parse_stock(m):
    try:
        price_str = m.get('z', '-')
        prev_str  = m.get('y', '-')
        price = float(price_str) if price_str not in ['-', '', None] else None
        prev  = float(prev_str)  if prev_str  not in ['-', '', None] else None
        change_pct = round((price - prev) / prev * 100, 2) if price and prev and prev > 0 else None
        vol_str = m.get('v', '')
        vol = round(float(vol_str)) if vol_str and vol_str != '-' else None
        return {
            'id':          m.get('c', ''),
            'name':        m.get('n', ''),
            'price':       round(price, 2) if price else None,
            'prev_close':  round(prev, 2)  if prev  else None,
            'change_pct':  change_pct,
            'high':        float(m.get('h') or 0) or None,
            'low':         float(m.get('l') or 0) or None,
            'vol':         vol,
            'is_realtime': price is not None,
        }
    except Exception as e:
        print(f'  解析錯誤 {m.get("c","?")}: {e}')
        return None

def main():
    now_utc = datetime.utcnow()
    now_tw_h = (now_utc.hour + 8) % 24
    print(f'=== 股價更新 {now_tw_h:02d}:{now_utc.minute:02d} 台北時間 ===')

    stocks = load_stocks()
    if not stocks:
        print('沒有股票清單，結束')
        return

    stock_ids = [s['id'] for s in stocks]
    name_map  = {s['id']: s['name'] for s in stocks}

    # 先試上市（TSE），沒抓到再試上櫃（OTC）
    result_map = {}
    for m in fetch_prices(stock_ids, 'tse'):
        parsed = parse_stock(m)
        if parsed and parsed['id']:
            result_map[parsed['id']] = parsed

    missing = [sid for sid in stock_ids if sid not in result_map]
    if missing:
        for m in fetch_prices(missing, 'otc'):
            parsed = parse_stock(m)
            if parsed and parsed['id']:
                result_map[parsed['id']] = parsed

    results = []
    for s in stocks:
        sid = s['id']
        if sid in result_map:
            entry = result_map[sid]
            if not entry['name']:
                entry['name'] = s['name']
            results.append(entry)
            if entry['price']:
                tag = '●即時' if entry['is_realtime'] else '○昨收'
                chg = f"{entry['change_pct']:+.2f}%" if entry['change_pct'] is not None else '—'
                print(f"  {tag} {sid} {entry['name']}: {entry['price']} ({chg})")
            else:
                print(f"  ✗ {sid} {s['name']}: 無資料")
        else:
            results.append({'id': sid, 'name': s['name'], 'price': None, 'prev_close': None,
                            'change_pct': None, 'high': None, 'low': None, 'vol': None, 'is_realtime': False})
            print(f"  ✗ {sid} {s['name']}: 無資料")

    output = {
        'updated_at':    now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'updated_at_tw': f'{now_tw_h:02d}:{now_utc.minute:02d}',
        'prices':        results
    }
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    rt = sum(1 for r in results if r['is_realtime'])
    print(f'\n✅ 完成！{rt}/{len(results)} 支即時報價，已存入 prices.json')

if __name__ == '__main__':
    main()
