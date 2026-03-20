"""
台股即時股價抓取腳本
- 從 stocks.json 讀取股票清單（新增股票只需改 stocks.json）
- 三重回補邏輯：z成交價 → b買進五檔 → a賣出五檔 → y昨收保底
- 由 GitHub Actions 每 5 分鐘執行一次（台北時間 09:00~13:30）
"""

import requests
import json
from datetime import datetime
import pytz

tw_tz = pytz.timezone('Asia/Taipei')

def now_tw():
    return datetime.now(tw_tz)

def load_stocks():
    """從 stocks.json 讀取股票清單，新增股票只需改這個檔案"""
    try:
        with open('stocks.json', 'r', encoding='utf-8') as f:
            stocks = json.load(f)
        print(f'載入 {len(stocks)} 支股票: {[s["id"] for s in stocks]}')
        return stocks
    except Exception as e:
        print(f'讀取 stocks.json 失敗: {e}')
        return []

def fetch_twse_prices(stock_ids, market='tse'):
    """抓取 TWSE/OTC 即時行情"""
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
    1. z：最近成交價（最即時）
    2. b：最佳五檔買進價第一筆
    3. a：最佳五檔賣出價第一筆
    4. y：昨收價（保底）
    """
    try:
        z_price = m.get('z')
        b_price = m.get('b', '').split('_')[0] if m.get('b') else None
        a_price = m.get('a', '').split('_')[0] if m.get('a') else None
        y_price = m.get('y', '-')

        def valid(v): return v and v not in ['-', '', None]

        z_val = z_price if valid(z_price) else None
        b_val = b_price if valid(b_price) else None
        a_val = a_price if valid(a_price) else None
        y_val = y_price if valid(y_price) else None

        current_price = z_val or b_val or a_val or y_val
        if not current_price:
            return None

        # 只要 z 有值就是即時成交價
        is_realtime = z_val is not None

        price = float(current_price)
        prev  = float(y_val) if y_val else None
        chg   = round((price - prev) / prev * 100, 2) if prev and prev > 0 else None

        vol_str = m.get('v', '0')
        vol = int(float(vol_str)) if valid(vol_str) else 0

        tag = '●即時' if is_realtime else '○回補'
        name = m.get('n', '') or name_override
        chg_str = f'({chg:+.2f}%)' if chg is not None else ''
        print(f'  {tag} {m.get("c","")} {name}: {price} {chg_str}')

        return {
            'id':          m.get('c', ''),
            'name':        name,
            'price':       round(price, 2),
            'prev_close':  round(prev, 2) if prev else None,
            'change_pct':  chg,
            'high':        float(m.get('h', 0) or 0) or None,
            'low':         float(m.get('l', 0) or 0) or None,
            'vol':         vol,
            'is_realtime': is_realtime,
        }
    except Exception as e:
        print(f'  解析錯誤 {m.get("c","?")}: {e}')
        return None

def main():
    t = now_tw()
    print(f'=== 股價更新 {t.strftime("%Y-%m-%d %H:%M:%S")} 台北時間 ===')

    stocks = load_stocks()
    if not stocks:
        print('沒有股票清單，結束')
        return

    stock_ids = [s['id'] for s in stocks]
    name_map  = {s['id']: s['name'] for s in stocks}

    # Step 1：先試上市（TSE）
    result_map = {}
    for m in fetch_twse_prices(stock_ids, 'tse'):
        sid = m.get('c', '').strip()
        if sid:
            parsed = parse_stock(m, name_map.get(sid, ''))
            if parsed:
                result_map[sid] = parsed

    # Step 2：沒抓到的改試上櫃（OTC）
    missing = [sid for sid in stock_ids if sid not in result_map]
    if missing:
        print(f'改試 OTC: {missing}')
        for m in fetch_twse_prices(missing, 'otc'):
            sid = m.get('c', '').strip()
            if sid:
                parsed = parse_stock(m, name_map.get(sid, ''))
                if parsed:
                    result_map[sid] = parsed

    # Step 3：整合，保持 stocks.json 順序
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
        'updated_at':    datetime.now(pytz.utc).isoformat(),
        'updated_at_tw': t.strftime('%H:%M'),
        'prices':        results
    }
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    rt = sum(1 for r in results if r['is_realtime'])
    print(f'\n✅ 完成！{rt}/{len(results)} 支即時報價，已存入 prices.json')

if __name__ == '__main__':
    main()
