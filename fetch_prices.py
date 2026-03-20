import requests
import json
from datetime import datetime
import pytz

# 設定台灣時區
tw_tz = pytz.timezone('Asia/Taipei')
now_tw = datetime.now(tw_tz)

# 妳要追蹤的股票清單
STOCK_LIST = ['2605', '2481', '6213', '8932', '2317', '2313', '2303', '2618', '2409']

def fetch_twse_prices(stocks):
    # 建立證交所 API URL
    stock_query = '|'.join([f'tse_{s}.tw' for s in stocks])
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={stock_query}&json=1&delay=0"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'msgArray' not in data:
            return []
        return data['msgArray']
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def parse_stock(m):
    try:
        # 核心修正：將 "-" 視為無效值，以觸發後續的補位邏輯
        z_price = m.get('z') if m.get('z') != '-' else None # 成交價
        b_price = m.get('b', '').split('_')[0] if m.get('b') and m.get('b') != '-' else None # 買進價
        a_price = m.get('a', '').split('_')[0] if m.get('a') and m.get('a') != '-' else None # 賣出價
        y_price = m.get('y', '-') # 昨收價

        # 決定最終顯示價格：成交價 > 買進價 > 賣出價 > 昨收價
        current_price = z_price or b_price or a_price or y_price
        
        # 只要 z, b, a 其中一個有值，且不是昨收，就判定為即時資料
        is_realtime = (z_price or b_price or a_price) and current_price != '-'

        return {
            "id": m.get('c'),
            "name": m.get('n'),
            "price": float(current_price) if current_price and current_price != '-' else None,
            "prev_close": float(y_price) if y_price != '-' else None,
            "change_pct": round(((float(current_price) - float(y_price)) / float(y_price)) * 100, 2) if current_price and y_price != '-' else None,
            "high": float(m.get('h', 0)) if m.get('h') and m.get('h') != '-' else None,
            "low": float(m.get('l', 0)) if m.get('l') and m.get('l') != '-' else None,
            "vol": int(m.get('v', 0)),
            "is_realtime": bool(is_realtime)
        }
    except Exception as e:
        print(f"Error parsing stock {m.get('c')}: {e}")
        return None

def main():
    print(f"Starting update at {now_tw.strftime('%Y-%m-%d %H:%M:%S')}")
    
    raw_data = fetch_twse_prices(STOCK_LIST)
    processed_prices = []
    
    for m in raw_data:
        parsed = parse_stock(m)
        if parsed:
            processed_prices.append(parsed)
            
    # 建立最終 JSON 格式
    output = {
        "updated_at": datetime.now(pytz.utc).isoformat(),
        "updated_at_tw": now_tw.strftime("%H:%M"),
        "prices": processed_prices
    }
    
    # 寫入檔案
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully updated prices.json with {len(processed_prices)} stocks.")

if __name__ == "__main__":
    main()
