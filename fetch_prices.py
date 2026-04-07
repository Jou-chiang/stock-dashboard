import json
import time
import requests
from datetime import datetime

# 讀取股票清單
with open("stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)

prices = {}

for stock in stocks:
    code = stock["id"]
    # Yahoo Finance 台股格式：代號.TW 或 代號.TWO
    for suffix in [".TW", ".TWO"]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=10)
            j = r.json()

            result = j.get("chart", {}).get("result", [])
            if not result:
                continue

            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if not price:
                continue

            prices[code] = {
                "price": price,
                "open": meta.get("regularMarketOpen", price),
                "high": meta.get("regularMarketDayHigh", price),
                "low": meta.get("regularMarketDayLow", price),
                "volume": meta.get("regularMarketVolume", 0),
                "change": round(price - meta.get("previousClose", price), 2),
                "change_pct": round((price - meta.get("previousClose", price)) / meta.get("previousClose", price) * 100, 2) if meta.get("previousClose") else 0,
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            print(f"✅ {code}{suffix}: {price}")
            break

        except Exception as e:
            print(f"❌ {code}{suffix}: {e}")
            continue

    time.sleep(0.3)

# 寫入 prices.json
if prices:
    output = {
        "prices": [
            {
                "id": code,
                "price": data["price"],
                "is_realtime": True,
                "vol": data["volume"] // 1000,
                "updated": data["updated"]
            }
            for code, data in prices.items()
        ]
    }
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ prices.json 更新完成，共 {len(prices)} 支")
else:
    print("⚠️ 無資料")
