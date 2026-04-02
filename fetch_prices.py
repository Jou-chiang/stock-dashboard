import os
import json
import time
from datetime import datetime
import shioaji as sj

# 從 GitHub Secrets 讀取 Key
api_key = os.environ["SHIOAJI_API_KEY"]
secret_key = os.environ["SHIOAJI_SECRET_KEY"]

# 讀取股票清單
with open("stocks.json", "r", encoding="utf-8") as f:
    stocks = json.load(f)

# 登入 Shioaji
api = sj.Shioaji()
api.login(api_key=api_key, secret_key=secret_key, fetch_contract=True)
time.sleep(10)  # 等待連線穩定

prices = {}

for stock in stocks:
    code = stock["id"]
    try:
        contract = api.Contracts.Stocks[code]
        snapshot = api.snapshots([contract])
        if snapshot:
            s = snapshot[0]
            prices[code] = {
                "price": s.close,
                "open": s.open,
                "high": s.high,
                "low": s.low,
                "volume": s.volume,
                "change": round(s.close - s.reference, 2),
                "change_pct": round((s.close - s.reference) / s.reference * 100, 2) if s.reference else 0,
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            print(f"✅ {code}: {s.close}")
        else:
            print(f"⚠️ {code}: 無資料")
    except Exception as e:
        print(f"❌ {code} 錯誤: {e}")

# 登出
api.logout()

# 寫入 prices.json
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(prices, f, ensure_ascii=False, indent=2)

print("✅ prices.json 更新完成")
